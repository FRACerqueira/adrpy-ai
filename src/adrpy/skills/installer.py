"""install/remove/list logic for adrpy-skills: resolves each (provider,
skill) pair to a real path, builds its content via that provider's wrap,
and checks/writes it through the content-hash drift marker -- see
ADR009V01."""

import re
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.errors import CommandError, FailureCodes, UsageError
from adrpy.core.hashing import build_marker, check_drift
from adrpy.core.fs import cleanup_orphaned_temp_files_for, read_bounded, read_with_permission_retry, unlink_with_retry
from adrpy.core.output import explain
from adrpy.core.security import is_within
from adrpy.core.text import strip_leading_boms
from adrpy.core.warnings import orphan_cleanup_warning, retry_warning
from adrpy.skills import resources
from adrpy.skills.providers import PROVIDERS, SHARED_DOC_PATH

_FRONTMATTER_RE = re.compile(r"\A(---\n.*?\n---\n)", re.DOTALL)

# Deliberately much larger than core/config.py's own CONFIG_READ_MAX_BYTES
# (64KB) -- that cap bounds a schema-fixed JSON file, this one bounds
# free-form AGENTS.md/SKILL.md content a project owner can legitimately
# grow well past that. Still bounded, not unlimited: an unbounded read
# of a planted 100MB file was measured peaking process memory near 200MB -- every other full-content reader in
# the project already caps for the same reason (see
# CONFIG_READ_MAX_BYTES); this was the one that didn't.
_READ_TEXT_MAX_BYTES = 10 * 1024 * 1024
_READ_TEXT_CHUNK_SIZE = 65536


def _package_version():
    try:
        return _pkg_version("adrpy-ai")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _read_text(path):
    """Reads `path` as UTF-8, retrying a transient PermissionError the
    same way every other reader in this project already does (core/
    config.py, core/lifecycle.py, all via core/fs.py)
    -- installer.py used to be the only reader that didn't, so a single
    transient contention blip (a Windows "pending delete" window under a
    concurrent reader) failed the whole install/remove/list call outright
    instead of being absorbed like everywhere else.

    Returns None if `path` doesn't exist -- whether it never existed, or
    vanished between an earlier `path.exists()` check and this read (a
    classic check-then-use TOCTOU window). Every caller in this module
    used to guard its own read with a separate `path.exists()` call
    first; two of the nine call sites didn't, and could raise a raw,
    uncaught `FileNotFoundError` if the file vanished in between --
    reachable even from `list`, a read-only command, and from `remove`
    AFTER it had already committed a real deletion for an earlier
    (provider, skill) pair in the same call, silently discarding that
    success from the caller's view. Folding the existence check into the
    read itself (one syscall attempt, not two) removes the window
    entirely instead of requiring every call site to close it on its
    own -- every one of them already treats "file not found" as "nothing
    installed here" via check_drift(None)/_agentsmd_block_state(None)/an
    explicit `is None` check, so this is a strict simplification, not a
    behavior change for the non-racing case.

    Bounded to _READ_TEXT_MAX_BYTES (see its own note): reads at most
    that many bytes plus one chunk's worth of overrun, used only to
    detect that the real file is larger, never decoded or returned.
    Raises a plain OSError when the cap is exceeded -- caught by
    skills/__main__.py's existing `except OSError` -> io-error, the same
    code a write failure already uses, rather than adding a second
    failure-code registry to a module that doesn't otherwise have one.

    Reading via `path.open("rb")` instead of `path.read_text()` drops
    Python's own default universal-newline translation, so the decode
    step below restores it by hand (`\\r\\n`/`\\r` -> `\\n`) -- on
    Windows, `atomic_write_text` writes `os.linesep` (CRLF) to disk.
    This, paired with `core/hashing.py`'s own `compute_hash` (which
    canonicalizes newlines to bare `\\n` before hashing),
    keeps hash-time and read-time content in agreement regardless of
    host OS: both sides always compare LF-canonical text."""

    try:
        raw_bytes = read_with_permission_retry(lambda: read_bounded(path, _READ_TEXT_MAX_BYTES, _READ_TEXT_CHUNK_SIZE))
    except FileNotFoundError:
        return None
    if len(raw_bytes) > _READ_TEXT_MAX_BYTES:
        raise OSError(f"{path}: exceeds the {_READ_TEXT_MAX_BYTES}-byte read limit for adrpy-skills.")
    try:
        text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as error:
        # An OSError, not a bare ValueError reaching __main__'s catch-all
        # as internal-error: the fix is the user's (re-save the file as
        # UTF-8 -- Windows PowerShell 5.1's `>` writes UTF-16), not a bug,
        # and the caller needs to know which file. Never decoded lossily:
        # AGENTS.md is rewritten from what is read here.
        raise OSError(
            f"{path}: not valid UTF-8 ({error.reason} at byte {error.start}); adrpy-skills only reads and "
            "writes UTF-8 -- re-save the file as UTF-8."
        ) from error
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _resolve_path(provider_name, skill_name, target_dir, scope):
    spec = PROVIDERS[provider_name]
    if scope == "global":
        template = spec["global_path"]
        if template is None:
            raise UsageError(f"--target global is not supported for provider '{provider_name}'.")
        return Path.home() / template[len("~/") :].format(name=skill_name)
    return Path(target_dir) / spec["project_path"].format(name=skill_name)


def _validate_scope(provider_names, scope):
    """Rejects an unrecognized --target value, and --target global for a
    provider without a global-scope concept, up front for every
    requested provider at once, before any write/removal begins -- a
    call naming several providers must never leave a partial effect on
    disk just because a later provider in the list turns out to be the
    one that fails.

    --provider/--skill both reject an unrecognized value via _expand_all();
    --target never did -- a typo (e.g. "golbal") silently fell through
    to the "project" branch in _resolve_path, writing into the current
    directory instead of failing loudly."""
    if scope not in ("project", "global"):
        raise UsageError(f"Unknown --target value: {scope!r}. Valid values: global, project.")
    if scope != "global":
        return
    unsupported = [name for name in provider_names if PROVIDERS[name]["global_path"] is None]
    if unsupported:
        supported = ", ".join(name for name, spec in PROVIDERS.items() if spec["global_path"] is not None)
        raise UsageError(
            f"--target global is not supported for provider(s): {', '.join(unsupported)}. "
            f"Use --provider {supported} (or omit --provider)."
        )


def _blocks_write(status, force):
    """A 'foreign' (no marker at all) or 'drifted' (marker present, hash
    no longer matches) file/block must never be silently written to or
    deleted without --force. 'malformed' (see _agentsmd_block_state) gets
    the same treatment -- it isn't safe to blindly replace or append to
    either."""
    return status in ("drifted", "foreign", "malformed") and not force


def _insert_marker(content, marker_version):
    """Places the marker immediately after a leading frontmatter block if
    one is present, otherwise at the very start -- the hash always covers
    `content` exactly as given, never the marker line itself.

    Must stay an exact inverse of `core.hashing.strip_marker` (which
    removes the marker line plus exactly one trailing newline): inserting
    `marker + "\\n"` and nothing else guarantees `strip_marker(insert_
    marker(content, v)) == content` for any content, so a freshly
    (re)generated file always re-hashes as "clean", never "drifted"."""
    marker = build_marker(marker_version, content)
    match = _FRONTMATTER_RE.match(content)
    if match:
        end = match.end()
        return content[:end] + marker + "\n" + content[end:]
    return marker + "\n" + content


def _shared_doc_path(target_dir, skill_name):
    return Path(target_dir) / SHARED_DOC_PATH.format(name=skill_name)


def _build_shared_doc_content(skill_name, full_content):
    return f"# {skill_name}\n\n{full_content}"


_AGENTSMD_BLOCK_TEMPLATE = "<!-- adrpy:skills:{name}:start -->\n{body}<!-- adrpy:skills:{name}:end -->\n"

# Matches any single tag line for any skill, one at a time -- no `.*`/DOTALL
# span-hunting across the file. A prior per-skill implementation (matching
# "start ... end" as one DOTALL span with `.search()`/`.finditer()`) cost
# O(n^2) against adversarial content with many `:start` tags and no `:end`
# anywhere (measured: ~9.5s against a 771KB crafted AGENTS.md, hit even by
# the read-only `list` command) -- this pattern can't backtrack that way
# since it never spans more than one tag. A tag is a whole line, as
# _AGENTSMD_BLOCK_TEMPLATE writes it: the same text quoted inside a line of
# the user's own prose is not a tag, and --force must never strip it.
# Trailing spaces/tabs are tolerated, and so is any run of BOMs at the very
# start of the file (skipped by offset, so a rewrite preserves them).
#
# Indentation is captured, not limited, because the shape of a line can't
# say who owns it: a block an editor re-indented and the
# user's quoted example look alike. Tags at 0-3 spaces are this tool's
# syntax, whatever surrounds them. Past that -- where CommonMark starts an
# indented code block -- only the block's own marker hash proves it is the
# tool's (see _agentsmd_locate); anything else there is the user's text.
_AGENTSMD_TAG_RE = re.compile(r"^([ \t]*)<!-- adrpy:skills:([^:\n]+):(start|end) -->[ \t]*(?:\n|\Z)", re.MULTILINE)
_AGENTSMD_CANONICAL_INDENT_RE = re.compile(r" {0,3}\Z")


def _agentsmd_tag_lines(file_text):
    """Every tag line at any indentation, in document order, as (name,
    kind, match_start, match_end, indent) tuples -- a single linear pass."""
    text = file_text or ""
    offset = len(text) - len(strip_leading_boms(text))
    return [
        (m.group(2), m.group(3), m.start() + offset, m.end() + offset, m.group(1))
        for m in _AGENTSMD_TAG_RE.finditer(text[offset:])
    ]


def _agentsmd_all_tags(file_text):
    """The tag lines at this tool's own position (0-3 spaces)."""
    return [t for t in _agentsmd_tag_lines(file_text) if _AGENTSMD_CANONICAL_INDENT_RE.match(t[4])]


def _agentsmd_own_tags(tags, skill_name):
    """This skill's own (start, end) tag tuples among `tags` when it has
    exactly one well-formed block, else None: more than one `:start`, more
    than one `:end`, a `:start` with no `:end`, a `:end` with no `:start`,
    in any combination, or another skill's tag between its own two (a
    nested or overlapping block, only reachable by hand-editing --
    replacing such a span would delete or split that other skill's
    block)."""
    mine = [t for t in tags if t[0] == skill_name]
    starts = [t for t in mine if t[1] == "start"]
    ends = [t for t in mine if t[1] == "end"]
    if len(starts) != 1 or len(ends) != 1 or starts[0][2] > ends[0][2]:
        return None
    if any(t[0] != skill_name and starts[0][3] <= t[2] < ends[0][2] for t in tags):
        return None
    return starts[0], ends[0]


def _dedent(text, indent):
    return "".join(line[len(indent):] if line.startswith(indent) else line for line in text.splitlines(keepends=True))


def _indent(text, indent):
    return "".join(indent + line if line.strip("\n") else line for line in text.splitlines(keepends=True))


def _agentsmd_locate(file_text, skill_name):
    """(state, span, indent, note, inner) for this skill's block in AGENTS.md.

    Tags at 0-3 spaces are this tool's syntax: `state` is check_drift's
    own verdict on the block's content (relative to its start tag's
    indentation), or "malformed" for a shape it can't safely rewrite.
    Only when there are none, an indented pair (same indentation) whose
    content hashes clean is the tool's block, re-indented by an editor.
    Any other indented copy is the user's text: "absent", with `note`
    saying why ("edited": its marker no longer matches; "unmarked": it
    has no valid marker; "unpaired": its indented tags are repeated,
    unpaired, at different indentations, or split by another skill's tag)
    so install/remove can say so.
    `inner` is the
    block's content between its tags, de-indented -- what was hashed."""
    text = file_text or ""
    tags = _agentsmd_tag_lines(text)
    canonical = [t for t in tags if _AGENTSMD_CANONICAL_INDENT_RE.match(t[4])]
    if any(t[0] == skill_name for t in canonical):
        own = _agentsmd_own_tags(canonical, skill_name)
        if own is None:
            return "malformed", None, "", None, None
        indent = own[0][4]
        inner = _dedent(text[own[0][3] : own[1][2]], indent)
        return check_drift(inner), (own[0][2], own[1][3]), indent, None, inner
    if not any(t[0] == skill_name for t in tags):
        return "absent", None, "", None, None
    own = _agentsmd_own_tags(tags, skill_name)
    if own is None or own[0][4] != own[1][4]:
        return "absent", None, "", "unpaired", None
    indent = own[0][4]
    inner = _dedent(text[own[0][3] : own[1][2]], indent)
    drift = check_drift(inner)
    if drift == "clean":
        return "clean", (own[0][2], own[1][3]), indent, None, inner
    if drift == "drifted":
        return "absent", None, "", "edited", None
    return "absent", None, "", "unmarked", None


def _agentsmd_skill_span(file_text, skill_name):
    """This skill's own complete block span -- (start, end) covering both
    tag lines and everything between them -- or None (see
    _agentsmd_locate)."""
    return _agentsmd_locate(file_text, skill_name)[1]


def _agentsmd_extract_inner(file_text, skill_name):
    """The block's own content, excluding the `start`/`end` wrapper lines
    and its indentation -- this is what was actually hashed (`marker +
    inner`), so drift checks must run against this, never the whole
    wrapped block. None when this skill has no block."""
    return _agentsmd_locate(file_text, skill_name)[4]


def _agentsmd_block_state(file_text, skill_name):
    """Like check_drift, for this skill's block in AGENTS.md (see
    _agentsmd_locate) -- "malformed" is blocked the same as a foreign file
    (see _blocks_write) instead of being touched."""
    return _agentsmd_locate(file_text, skill_name)[0]


def _agentsmd_is_indented(file_text, skill_name):
    """True when this skill's block is an indented copy adopted by its
    marker hash, not one at the tool's own position."""
    indent = _agentsmd_locate(file_text, skill_name)[2]
    return not _AGENTSMD_CANONICAL_INDENT_RE.match(indent)


def _agentsmd_user_copy_warning(file_text, skill_name):
    """The warning for an indented copy treated as the user's own text, or
    None."""
    note = _agentsmd_locate(file_text, skill_name)[3]
    if note is None:
        return None
    why = {
        "edited": "its marker no longer matches (edited)",
        "unmarked": "it carries no valid marker",
        "unpaired": "its tags are repeated, unpaired, at different indentations, or split by another skill's tag",
    }[note]
    return (
        f"agentsmd/{skill_name}: an indented copy of its tags is treated as your own text, since {why}; "
        "left untouched."
    )


def _agentsmd_replace_or_append(file_text, skill_name, new_block):
    _state, span, indent, _note, _inner = _agentsmd_locate(file_text, skill_name)
    if span is not None:
        start, end = span
        return file_text[:start] + _indent(new_block, indent) + file_text[end:]
    return _agentsmd_append(file_text, new_block)


def _agentsmd_append(file_text, new_block):
    if not file_text:
        return new_block
    sep = "\n" if file_text.endswith("\n") else "\n\n"
    return file_text + sep + new_block


def _agentsmd_remove_block(file_text, skill_name):
    span = _agentsmd_skill_span(file_text, skill_name)
    if span is None:
        return file_text
    start, end = span
    return file_text[:start] + file_text[end:]


def _agentsmd_force_strip_all(file_text, skill_name):
    """Removes every one of this skill's own tag lines from `file_text`,
    however malformed the surrounding structure (truncated, duplicated,
    out of order) -- used only when `--force` overrides a "malformed"
    _agentsmd_block_state, so a fresh block can be written in without a
    stray tag left behind that a later single-block parse could misread.

    Deliberately removes only the tag lines themselves, precisely located
    by the linear tag scan -- never a guessed span of surrounding content.
    A truncated block's own orphaned body text (between a lone `:start`
    and wherever the file happens to continue) has no reliably knowable
    end boundary; guessing one is exactly the defect this replaces (the
    prior greedy-regex version deleted through to the next thing that
    merely looked like a boundary, including another skill's own valid
    block or the user's own hand-written content past it)."""
    tags = [t for t in _agentsmd_all_tags(file_text) if t[0] == skill_name]
    if not tags:
        return file_text
    pieces = []
    cursor = 0
    for _, _, tag_start, tag_end, _ in tags:
        pieces.append(file_text[cursor:tag_start])
        cursor = tag_end
    pieces.append(file_text[cursor:])
    return "".join(pieces)


def _stub_writable(provider_name, skill_name, target_dir, scope, force):
    """Whether install would write this stub-mode provider's own file."""
    path = _resolve_path(provider_name, skill_name, target_dir, scope)
    text = _read_text(path)
    status = _agentsmd_block_state(text, skill_name) if provider_name == "agentsmd" else check_drift(text)
    return not _blocks_write(status, force)


def _other_stub_providers_reference(target_dir, skill_name, scope, exclude_provider, warnings=None):
    """True if some OTHER stub-mode provider (already installed, not part
    of this same call, or part of it but not the one being removed) still
    points at the shared doc for this skill. A malformed agentsmd block
    still counts as "referencing" the skill -- it's evidence the skill is
    still (unsafely) present there, not evidence it's gone. So does an
    AGENTS.md this call can't read (not UTF-8, over the read limit): the
    shared doc is kept, with a warning, rather than failing a remove that
    never asked to touch AGENTS.md."""
    for provider_name, spec in PROVIDERS.items():
        if provider_name == exclude_provider or spec["mode"] not in ("stub", "stub_block"):
            continue
        if scope == "global" and spec["global_path"] is None:
            continue
        path = _resolve_path(provider_name, skill_name, target_dir, scope)
        if provider_name == "agentsmd":
            try:
                agents_text = _read_text(path)
            except OSError as error:
                if warnings is not None:
                    warnings.append(
                        f"shared-doc/{skill_name}: kept -- AGENTS.md could not be read to check whether it still "
                        f"points at it ({explain(error)})."
                    )
                return True
            if _agentsmd_block_state(agents_text, skill_name) != "absent":
                return True
            # Body text a --force cleanup of a malformed block left in place
            # (see _agentsmd_force_strip_all), or the user's own prose, still
            # points readers here -- in any separator or letter case, since
            # keeping the doc is the safe side of a mismatch.
            shared_rel = SHARED_DOC_PATH.format(name=skill_name).lower()
            if agents_text and shared_rel in agents_text.replace("\\", "/").lower():
                return True
        elif path.exists():
            return True
    return False


def _expand_problem(names, universe, flag):
    """The usage problem with one --provider/--skill value list, or None."""
    if names == ["all"]:
        return None
    if not names:
        return f"No {flag} values given (empty after splitting on comma)."
    unknown = [name for name in names if name not in universe]
    if unknown:
        return f"Unknown {flag} value(s): {', '.join(unknown)}. Valid values: {', '.join(sorted(universe))}."
    return None


def _expand_all(providers, skills, scope=None, retired=False):
    """Validates --provider, --skill and (when given) --target together,
    reporting every problem in one usage-error instead of stopping at the
    first flag. With `retired`, --skill also accepts (and 'all' also
    covers) the skills an older version shipped."""
    skill_universe = resources.SKILL_NAMES + (resources.RETIRED_SKILL_NAMES if retired else ())
    target_problem = None
    if scope is not None and scope not in ("project", "global"):
        target_problem = f"Unknown --target value: {scope!r}. Valid values: global, project."
    elif scope == "global":
        # Known names only: an unknown one is reported by the --provider check.
        chosen = list(PROVIDERS) if providers == ["all"] else [name for name in providers if name in PROVIDERS]
        unsupported = [name for name in dict.fromkeys(chosen) if PROVIDERS[name]["global_path"] is None]
        if unsupported:
            supported = ", ".join(name for name, spec in PROVIDERS.items() if spec["global_path"] is not None)
            target_problem = (
                f"--target global is not supported for provider(s): {', '.join(unsupported)}. "
                f"Use --provider {supported} (or omit --provider)."
            )
    problems = [
        problem
        for problem in (
            _expand_problem(providers, PROVIDERS, "--provider"),
            _expand_problem(skills, skill_universe, "--skill"),
            target_problem,
        )
        if problem
    ]
    if problems:
        raise UsageError(" ".join(problems))
    expand = lambda names, universe: list(universe) if names == ["all"] else list(dict.fromkeys(names))  # noqa: E731
    return expand(providers, PROVIDERS), expand(skills, skill_universe)


def _require_target_dir(target_dir, scope):
    """A --path that doesn't exist is a typo, not a request to create a
    new directory tree -- refused the same way adrpy's own commands refuse
    it. Irrelevant for --target global, which never writes under --path."""
    if scope == "project" and not Path(target_dir).is_dir():
        raise CommandError(
            FailureCodes.TARGET_DIRECTORY_NOT_FOUND,
            f"{target_dir}: not an existing directory; nothing was written.",
            data={"path": str(target_dir)},
        )


def _write_surface(target_dir, provider_names, skill_names, scope):
    """Every file this install/remove call may write or delete: each
    provider x skill path, plus the shared doc when a stub provider is
    involved."""
    paths = [_resolve_path(provider, skill, target_dir, scope) for skill in skill_names for provider in provider_names]
    if any(PROVIDERS[name]["mode"] != "full" for name in provider_names):
        paths.extend(_shared_doc_path(target_dir, skill) for skill in skill_names)
    return paths


def _reject_paths_leaving_the_target(paths, target_dir, scope, allow_external_links):
    """A junction or symlink planted inside --path (or under the home
    directory, for --target global) would otherwise redirect writes and
    deletes outside it -- reproduced: remove deleted a tool-written file in
    another directory, reported under the in-repo path, with no --force.
    Every path must resolve inside the target, before any side effect,
    the same real-path containment the core CLI applies to its own
    folders (core/security.py). Opting out is explicit: a dotfiles setup
    linking ~/.claude or .claude/skills elsewhere is legitimate, and
    --allow-external-links says so."""
    if allow_external_links:
        return
    base = Path.home() if scope == "global" else Path(target_dir)
    resolved_base = base.resolve()
    for path in paths:
        if not is_within(base, path, resolved_base=resolved_base):
            raise CommandError(
                FailureCodes.PATH_OUTSIDE_REPOSITORY,
                f"{path} resolves to {path.resolve()}, outside {resolved_base} (through a link); nothing was "
                "written or removed. Pass --allow-external-links if that link is intended.",
                data={"file": str(path), "resolved": str(path.resolve())},
            )


def _cleanup_orphaned_temp_files(target_dir, provider_names, skill_names, scope, warnings):
    """Sweeps the temp files an earlier interrupted write of this same
    request could have left behind, like the 8 core `adrpy` mutating
    commands do for their own folder -- but only the exact
    `<name>.<16 or 32 hex>.tmp` next to each file this call writes, never a
    folder-wide scan: every folder written here (the repository root,
    `.github/instructions/`, `~/.claude/skills/`) also holds content
    this tool never wrote."""
    paths = _write_surface(target_dir, provider_names, skill_names, scope)
    base = Path.home() if scope == "global" else Path(target_dir)
    warning = orphan_cleanup_warning(cleanup_orphaned_temp_files_for(paths, warnings=warnings), relative_to=base)
    if warning:
        warnings.append(warning)


@contextmanager
def _report_partial_effects(data, warnings):
    """install()/remove() write and delete several files in one call. A
    failure partway through must still tell the caller what that call
    already changed on disk (`data` -- the same installed/removed/skipped
    lists the success result carries, as far as they got) and the
    warnings already collected, the same way core/warnings.py's
    attach_warnings does for adrpy's own commands."""
    try:
        yield
    except OSError as error:
        raise CommandError(FailureCodes.IO_ERROR, explain(error), data=data, warnings=list(warnings)) from error
    except KeyboardInterrupt as error:
        raise CommandError("interrupted", "Interrupted (Ctrl+C).", data=data, warnings=list(warnings)) from error


def install(target_dir, providers, skills, scope, force, allow_external_links=False):
    provider_names, skill_names = _expand_all(providers, skills, scope)
    _validate_scope(provider_names, scope)
    _require_target_dir(target_dir, scope)
    _reject_paths_leaving_the_target(
        _write_surface(target_dir, provider_names, skill_names, scope), target_dir, scope, allow_external_links
    )
    marker_version = _package_version()
    installed = []
    skipped = []
    warnings = []
    with _report_partial_effects({"installed": installed, "skipped": skipped}, warnings):
        _cleanup_orphaned_temp_files(target_dir, provider_names, skill_names, scope, warnings)

        for skill_name in skill_names:
            meta = resources.load_meta(skill_name)
            full_content = resources.load_full_content(skill_name)
            shared_doc_rel = SHARED_DOC_PATH.format(name=skill_name)
            # Derivable from the request alone, no I/O needed -- computed (and
            # the shared doc written, below) BEFORE any stub-mode provider's
            # own file, so an interruption partway through the provider loop
            # can never leave a stub already pointing at a shared doc that was
            # never written. Previously this was only known as a side effect
            # of the provider loop, and the shared doc was written only after
            # it finished -- reproduced: interrupting between two stub
            # providers left the first one's file referencing a nonexistent
            # doc/ai-skills/<name>.md, with list_installed() reporting it as
            # drifted: false regardless.
            needs_shared_doc = any(PROVIDERS[name]["mode"] != "full" for name in provider_names)

            # Tracked explicitly (not re-derived from `skipped`) so the
            # provider loop below can refuse to write any stub-mode provider's
            # own file when the shared doc it would reference wasn't written --
            # a blocked shared-doc write used to be silently disconnected from
            # whether the providers depending on it were allowed to proceed.
            shared_doc_blocked = False
            # A new shared doc only when some stub-mode provider in this call
            # will actually be written -- otherwise nothing would point at it,
            # and no later remove would ever find a reason to delete it.
            if needs_shared_doc and not _shared_doc_path(target_dir, skill_name).exists():
                needs_shared_doc = any(
                    PROVIDERS[name]["mode"] != "full" and _stub_writable(name, skill_name, target_dir, scope, force)
                    for name in provider_names
                )
            if needs_shared_doc:
                shared_path = _shared_doc_path(target_dir, skill_name)
                shared_status = check_drift(_read_text(shared_path))
                shared_doc_blocked = _blocks_write(shared_status, force)
                if shared_doc_blocked:
                    skipped.append({"provider": "shared-doc", "skill": skill_name, "file": str(shared_path), "reason": shared_status})
                else:
                    if force and shared_status in ("drifted", "foreign"):
                        warnings.append(f"shared-doc/{skill_name}: {shared_status}, overwritten (--force).")
                    shared_content = _insert_marker(_build_shared_doc_content(skill_name, full_content), marker_version)
                    shared_path.parent.mkdir(parents=True, exist_ok=True)
                    attempts = atomic_write_text(shared_path, shared_content)
                    warning = retry_warning(attempts)
                    if warning:
                        # retry_warning's own message carries no file identity --
                        # fine for every other caller in this project (one write
                        # per command invocation), but install()/remove() can
                        # write several files in one call, where an unqualified
                        # "write succeeded only after N attempts" doesn't say
                        # which one.
                        warnings.append(f"shared-doc/{skill_name}: {warning}")
                    # Symmetric with remove()'s own shared-doc reporting --
                    # previously this write's own success never appeared
                    # anywhere in the result, even in the plain happy path.
                    installed.append({"provider": "shared-doc", "skill": skill_name, "file": str(shared_path)})

            for provider_name in provider_names:
                spec = PROVIDERS[provider_name]
                path = _resolve_path(provider_name, skill_name, target_dir, scope)

                # A stub-mode provider's own file is meaningless without the
                # shared doc it points readers at -- never write one pointing
                # at a shared doc that was itself just refused (foreign/
                # drifted, no --force). Previously nothing connected the two:
                # a blocked shared-doc write didn't stop a stub provider from
                # reporting a clean success while pointing at stale content.
                if spec["mode"] != "full" and shared_doc_blocked:
                    skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": "shared-doc-blocked"})
                    continue

                if provider_name == "agentsmd":
                    existing_file = _read_text(path)
                    status = _agentsmd_block_state(existing_file, skill_name)
                    copy_warning = _agentsmd_user_copy_warning(existing_file, skill_name)
                    if copy_warning:
                        warnings.append(copy_warning)
                    if _blocks_write(status, force):
                        skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                        continue
                    if force and status in ("drifted", "foreign"):
                        warnings.append(f"agentsmd/{skill_name}: {status}, overwritten (--force).")
                    if force and status == "malformed":
                        # Not "overwritten" -- _agentsmd_force_strip_all only
                        # ever removes this skill's own tag lines, never a
                        # guessed span of orphaned body text between them (see
                        # its own docstring for why). That text survives,
                        # unwrapped, immediately before the freshly written
                        # block -- say so, rather than implying it's gone.
                        warnings.append(
                            f"agentsmd/{skill_name}: malformed, tags replaced (--force) -- any orphaned body text "
                            "between them was left in place, since its true boundary can't be determined safely."
                        )
                    if status == "malformed":
                        existing_file = _agentsmd_force_strip_all(existing_file, skill_name)
                    inner = spec["wrap"](skill_name, meta, None, shared_doc_rel)
                    marker = build_marker(marker_version, inner)
                    body = marker + "\n" + inner
                    new_block = _AGENTSMD_BLOCK_TEMPLATE.format(name=skill_name, body=body)
                    if status == "malformed":
                        # Decided on the file as found: re-locating after the
                        # strip would adopt an indented copy the user wrote,
                        # which the 0-3-space tags made their own text.
                        new_file = _agentsmd_append(existing_file, new_block)
                    else:
                        new_file = _agentsmd_replace_or_append(existing_file, skill_name, new_block)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    attempts = atomic_write_text(path, new_file)
                    warning = retry_warning(attempts)
                    if warning:
                        warnings.append(f"agentsmd/{skill_name}: {warning}")
                    installed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
                    continue

                existing = _read_text(path)
                status = check_drift(existing)
                if _blocks_write(status, force):
                    skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                    continue
                if force and status in ("drifted", "foreign"):
                    warnings.append(f"{provider_name}/{skill_name}: {status}, overwritten (--force).")

                if spec["mode"] == "full":
                    wrapped = spec["wrap"](skill_name, meta, full_content, None)
                else:
                    wrapped = spec["wrap"](skill_name, meta, None, shared_doc_rel)
                content = _insert_marker(wrapped, marker_version)
                path.parent.mkdir(parents=True, exist_ok=True)
                attempts = atomic_write_text(path, content)
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(f"{provider_name}/{skill_name}: {warning}")
                installed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})

    return {"installed": installed, "skipped": skipped, "warnings": warnings}


def remove(target_dir, providers, skills, scope, force, allow_external_links=False):
    provider_names, skill_names = _expand_all(providers, skills, scope, retired=True)
    _validate_scope(provider_names, scope)
    _require_target_dir(target_dir, scope)
    _reject_paths_leaving_the_target(
        _write_surface(target_dir, provider_names, skill_names, scope), target_dir, scope, allow_external_links
    )
    removed = []
    skipped = []
    warnings = []
    with _report_partial_effects({"removed": removed, "skipped": skipped}, warnings):
        _cleanup_orphaned_temp_files(target_dir, provider_names, skill_names, scope, warnings)

        for skill_name in skill_names:
            any_stub_removed = False

            for provider_name in provider_names:
                spec = PROVIDERS[provider_name]

                if provider_name == "agentsmd":
                    path = _resolve_path(provider_name, skill_name, target_dir, scope)
                    file_text = _read_text(path)
                    if file_text is None:
                        warnings.append(f"agentsmd/{skill_name}: not installed, nothing to remove.")
                        continue
                    status = _agentsmd_block_state(file_text, skill_name)
                    if status == "absent":
                        warnings.append(
                            _agentsmd_user_copy_warning(file_text, skill_name)
                            or f"agentsmd/{skill_name}: not installed, nothing to remove."
                        )
                        continue
                    if not force and _agentsmd_is_indented(file_text, skill_name):
                        # Proven the tool's by its hash, but byte for byte what
                        # a verbatim copy the user quoted would also be -- so
                        # deleting it takes --force.
                        skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": "indented"})
                        warnings.append(
                            f"agentsmd/{skill_name}: its block is indented as a code block and may be your own "
                            "verbatim copy; removed only with --force."
                        )
                        continue
                    if _blocks_write(status, force):
                        skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                        continue
                    if status == "malformed":
                        # _agentsmd_remove_block's single-match, non-greedy pattern
                        # can't reliably remove a truncated or duplicated block --
                        # only reachable here via --force, same as install()'s own
                        # malformed-cleanup path.
                        new_file = _agentsmd_force_strip_all(file_text, skill_name)
                        warnings.append(
                            f"agentsmd/{skill_name}: malformed, tags removed (--force) -- any orphaned body text "
                            "between them was left in place, since its true boundary can't be determined safely; "
                            "while it still names the shared doc, that doc is kept."
                        )
                    else:
                        new_file = _agentsmd_remove_block(file_text, skill_name)
                    # Never delete AGENTS.md itself, even if this empties it --
                    # that's a judgment call for the human, not this command.
                    attempts = atomic_write_text(path, new_file)
                    warning = retry_warning(attempts)
                    if warning:
                        warnings.append(f"agentsmd/{skill_name}: {warning}")
                    removed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
                    any_stub_removed = True
                    continue

                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                existing = _read_text(path)
                if existing is None:
                    warnings.append(f"{provider_name}/{skill_name}: not installed, nothing to remove.")
                    continue
                status = check_drift(existing)
                if _blocks_write(status, force):
                    skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                    continue
                unlink_with_retry(path)
                removed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
                if spec["mode"] in ("stub", "stub_block"):
                    any_stub_removed = True

            # Also when no stub was removed in this call: a shared doc left by
            # an interrupted install, or whose stub was deleted by hand, has
            # no other way to be removed.
            if any_stub_removed or any(PROVIDERS[name]["mode"] != "full" for name in provider_names):
                warnings_before = len(warnings)
                still_referenced = _other_stub_providers_reference(target_dir, skill_name, scope, None, warnings)
                if (
                    still_referenced
                    and any_stub_removed
                    and len(warnings) == warnings_before
                    and _shared_doc_path(target_dir, skill_name).exists()
                ):
                    warnings.append(
                        f"shared-doc/{skill_name}: kept -- another stub-mode provider, or text in AGENTS.md, "
                        "still points at it."
                    )
                if not still_referenced:
                    shared_path = _shared_doc_path(target_dir, skill_name)
                    shared_existing = _read_text(shared_path)
                    shared_status = check_drift(shared_existing)
                    # With no stub removed in this call, only a shared doc the
                    # tool itself wrote (it carries the marker) is in scope --
                    # a file the user wrote at that path is never reported,
                    # and never deleted, even with --force.
                    if shared_status == "foreign" and not any_stub_removed:
                        shared_status = "absent"
                    if shared_status != "absent":
                        if _blocks_write(shared_status, force):
                            skipped.append(
                                {"provider": "shared-doc", "skill": skill_name, "file": str(shared_path), "reason": shared_status}
                            )
                        else:
                            unlink_with_retry(shared_path)
                            removed.append({"provider": "shared-doc", "skill": skill_name, "file": str(shared_path)})

    return {"removed": removed, "skipped": skipped, "warnings": warnings}


def list_installed(target_dir, providers, skills):
    provider_names, skill_names = _expand_all(providers, skills, retired=True)
    _require_target_dir(target_dir, "project")
    rows = []

    # Mirrors install()/remove()'s own `needs_shared_doc` -- the one
    # shared doc/ai-skills/<name>.md file a stub-mode provider's stub
    # points at is its own row here too, same as it's its own row in
    # `installed`/`removed` (provider "shared-doc"), instead of being
    # invisible to `list` even though a blocked/drifted shared doc is
    # exactly what would later cause install's own "shared-doc-blocked"
    # skip.
    needs_shared_doc = any(PROVIDERS[name]["mode"] != "full" for name in provider_names)

    for skill_name in skill_names:
        if needs_shared_doc:
            shared_path = _shared_doc_path(target_dir, skill_name)
            shared_existing = _read_text(shared_path)
            shared_status = check_drift(shared_existing)
            # Same scope as remove: a file with no marker that no stub
            # points at is the user's own, not a shared doc of this tool.
            if shared_status == "foreign" and not _other_stub_providers_reference(target_dir, skill_name, "project", None):
                shared_status = "absent"
            shared_installed = shared_status != "absent"
            shared_drifted = None if not shared_installed else shared_status in ("drifted", "foreign")
            rows.append(
                {
                    "skill": skill_name,
                    "provider": "shared-doc",
                    "scope": "project",
                    "installed": shared_installed,
                    "drifted": shared_drifted,
                    "file": str(shared_path),
                }
            )
        for provider_name in provider_names:
            spec = PROVIDERS[provider_name]
            scopes = ("project", "global") if provider_name == "claude" else ("project",)
            for scope in scopes:
                if scope == "global" and spec["global_path"] is None:
                    continue
                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                if provider_name == "agentsmd":
                    file_text = _read_text(path)
                    status = _agentsmd_block_state(file_text, skill_name)
                    installed_flag = status != "absent"
                    # "foreign"/"malformed" count as drifted here too: all mean
                    # install/remove would refuse to touch this path without
                    # --force, which is the one thing this boolean needs to tell
                    # the caller.
                    drifted = None if not installed_flag else status in ("drifted", "foreign", "malformed")
                else:
                    existing = _read_text(path)
                    installed_flag = existing is not None
                    drifted = None if not installed_flag else check_drift(existing) in ("drifted", "foreign")
                rows.append(
                    {
                        "skill": skill_name,
                        "provider": provider_name,
                        "scope": scope,
                        "installed": installed_flag,
                        "drifted": drifted,
                        "file": str(path),
                    }
                )

    if skills == ["all"]:
        # A retired skill is listed under 'all' only where something of it is still on disk.
        rows = [row for row in rows if row["skill"] not in resources.RETIRED_SKILL_NAMES or row["installed"]]
    return {"skills": rows, "warnings": []}
