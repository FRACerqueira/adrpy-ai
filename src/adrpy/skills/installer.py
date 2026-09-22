"""install/remove/list logic for adrpy-skills: resolves each (provider,
skill) pair to a real path, builds its content via that provider's wrap,
and checks/writes it through the content-hash drift marker -- see
ADR009V01."""

import re
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from pathlib import Path

from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.errors import UsageError
from adrpy.core.hashing import build_marker, check_drift
from adrpy.skills import resources
from adrpy.skills.providers import PROVIDERS, SHARED_DOC_PATH

_FRONTMATTER_RE = re.compile(r"\A(---\n.*?\n---\n)", re.DOTALL)


def _package_version():
    try:
        return _pkg_version("adrpy-ai")
    except PackageNotFoundError:
        return "0.0.0+dev"


def _resolve_path(provider_name, skill_name, target_dir, scope):
    spec = PROVIDERS[provider_name]
    if scope == "global":
        template = spec["global_path"]
        if template is None:
            raise UsageError(f"--target global is not supported for provider '{provider_name}'.")
        return Path.home() / template[len("~/") :].format(name=skill_name)
    return Path(target_dir) / spec["project_path"].format(name=skill_name)


def _validate_scope(provider_names, scope):
    """Rejects --target global up front, for every requested provider at
    once, before any write/removal begins -- a call naming several
    providers must never leave a partial effect on disk just because a
    later provider in the list turns out to be the one that fails."""
    if scope != "global":
        return
    unsupported = [name for name in provider_names if PROVIDERS[name]["global_path"] is None]
    if unsupported:
        raise UsageError(f"--target global is not supported for provider(s): {', '.join(unsupported)}.")


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
# since it never spans more than one tag.
_AGENTSMD_TAG_RE = re.compile(r"<!-- adrpy:skills:([^:\n]+):(start|end) -->\n?")


def _agentsmd_all_tags(file_text):
    """Every adrpy:skills marker tag in `file_text`, in document order, as
    (name, kind, match_start, match_end) tuples -- a single linear pass."""
    return [(m.group(1), m.group(2), m.start(), m.end()) for m in _AGENTSMD_TAG_RE.finditer(file_text or "")]


def _agentsmd_skill_span(file_text, skill_name):
    """This skill's own complete block span -- (start, end) covering both
    tag lines and everything between them -- or None when this skill has
    no single well-formed block (absent, or malformed: more than one
    `:start`, more than one `:end`, a `:start` with no `:end`, or a
    `:end` with no `:start`, in any combination)."""
    tags = [t for t in _agentsmd_all_tags(file_text) if t[0] == skill_name]
    starts = [t for t in tags if t[1] == "start"]
    ends = [t for t in tags if t[1] == "end"]
    if len(starts) != 1 or len(ends) != 1 or starts[0][2] > ends[0][2]:
        return None
    return starts[0][2], ends[0][3]


def _agentsmd_extract_inner(file_text, skill_name):
    """The block's own content, excluding the `start`/`end` wrapper lines
    -- this is what was actually hashed (`marker + inner`), so drift
    checks must run against this, never the whole wrapped block. None when
    this skill has no single well-formed block."""
    tags = [t for t in _agentsmd_all_tags(file_text) if t[0] == skill_name]
    starts = [t for t in tags if t[1] == "start"]
    ends = [t for t in tags if t[1] == "end"]
    if len(starts) != 1 or len(ends) != 1 or starts[0][2] > ends[0][2]:
        return None
    return file_text[starts[0][3] : ends[0][2]]


def _agentsmd_block_state(file_text, skill_name):
    """Like check_drift, but first detects malformed shapes unique to
    AGENTS.md's marked-block format (see _agentsmd_skill_span) -- reported
    as "malformed" and blocked the same as a foreign file (see
    _blocks_write) instead of being touched."""
    text = file_text or ""
    if any(t[0] == skill_name for t in _agentsmd_all_tags(text)) and _agentsmd_skill_span(text, skill_name) is None:
        return "malformed"
    return check_drift(_agentsmd_extract_inner(text, skill_name))


def _agentsmd_replace_or_append(file_text, skill_name, new_block):
    span = _agentsmd_skill_span(file_text, skill_name)
    if span is not None:
        start, end = span
        return file_text[:start] + new_block + file_text[end:]
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
    for _, _, tag_start, tag_end in tags:
        pieces.append(file_text[cursor:tag_start])
        cursor = tag_end
    pieces.append(file_text[cursor:])
    return "".join(pieces)


def _agentsmd_has_any_block(file_text):
    return bool(re.search(r"<!-- adrpy:skills:[^:]+:start -->", file_text or ""))


def _other_stub_providers_reference(target_dir, skill_name, scope, exclude_provider, providers_in_target):
    """True if some OTHER stub-mode provider (already installed, not part
    of this same call, or part of it but not the one being removed) still
    points at the shared doc for this skill. A malformed agentsmd block
    still counts as "referencing" the skill -- it's evidence the skill is
    still (unsafely) present there, not evidence it's gone."""
    for provider_name, spec in PROVIDERS.items():
        if provider_name == exclude_provider or spec["mode"] not in ("stub", "stub_block"):
            continue
        if scope == "global" and spec["global_path"] is None:
            continue
        path = _resolve_path(provider_name, skill_name, target_dir, scope)
        if provider_name == "agentsmd":
            if path.exists() and _agentsmd_block_state(path.read_text(encoding="utf-8"), skill_name) != "absent":
                return True
        elif path.exists():
            return True
    return False


def _expand(names, universe):
    if names == ["all"]:
        return list(universe)
    if not names:
        raise UsageError("No values given (empty after splitting on comma).")
    unknown = [name for name in names if name not in universe]
    if unknown:
        raise UsageError(f"Unknown value(s): {', '.join(unknown)}. Valid values: {', '.join(sorted(universe))}.")
    return list(dict.fromkeys(names))


def install(target_dir, providers, skills, scope, force):
    provider_names = _expand(providers, PROVIDERS)
    skill_names = _expand(skills, resources.SKILL_NAMES)
    _validate_scope(provider_names, scope)
    marker_version = _package_version()
    installed = []
    skipped = []
    warnings = []

    for skill_name in skill_names:
        meta = resources.load_meta(skill_name)
        full_content = resources.load_full_content(skill_name)
        shared_doc_rel = SHARED_DOC_PATH.format(name=skill_name)
        needs_shared_doc = False

        for provider_name in provider_names:
            spec = PROVIDERS[provider_name]

            if provider_name == "agentsmd":
                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                existing_file = path.read_text(encoding="utf-8") if path.exists() else ""
                status = _agentsmd_block_state(existing_file, skill_name)
                if _blocks_write(status, force):
                    skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                    continue
                if force and status in ("drifted", "foreign", "malformed"):
                    warnings.append(f"agentsmd/{skill_name}: {status}, overwritten (--force).")
                if status == "malformed":
                    existing_file = _agentsmd_force_strip_all(existing_file, skill_name)
                inner = spec["wrap"](skill_name, meta, None, shared_doc_rel)
                marker = build_marker(marker_version, inner)
                body = marker + "\n" + inner
                new_block = _AGENTSMD_BLOCK_TEMPLATE.format(name=skill_name, body=body)
                new_file = _agentsmd_replace_or_append(existing_file, skill_name, new_block)
                path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(path, new_file)
                installed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
                needs_shared_doc = True
                continue

            path = _resolve_path(provider_name, skill_name, target_dir, scope)
            existing = path.read_text(encoding="utf-8") if path.exists() else None
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
                needs_shared_doc = True
            content = _insert_marker(wrapped, marker_version)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(path, content)
            installed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})

        if needs_shared_doc:
            shared_path = _shared_doc_path(target_dir, skill_name)
            shared_existing = shared_path.read_text(encoding="utf-8") if shared_path.exists() else None
            shared_status = check_drift(shared_existing)
            if _blocks_write(shared_status, force):
                skipped.append({"provider": "shared-doc", "skill": skill_name, "file": str(shared_path), "reason": shared_status})
            else:
                if force and shared_status in ("drifted", "foreign"):
                    warnings.append(f"shared-doc/{skill_name}: {shared_status}, overwritten (--force).")
                shared_content = _insert_marker(_build_shared_doc_content(skill_name, full_content), marker_version)
                shared_path.parent.mkdir(parents=True, exist_ok=True)
                atomic_write_text(shared_path, shared_content)

    return {"installed": installed, "skipped": skipped, "warnings": warnings}


def remove(target_dir, providers, skills, scope, force):
    provider_names = _expand(providers, PROVIDERS)
    skill_names = _expand(skills, resources.SKILL_NAMES)
    _validate_scope(provider_names, scope)
    removed = []
    skipped = []
    warnings = []

    for skill_name in skill_names:
        any_stub_removed = False

        for provider_name in provider_names:
            spec = PROVIDERS[provider_name]

            if provider_name == "agentsmd":
                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                if not path.exists():
                    warnings.append(f"agentsmd/{skill_name}: not installed, nothing to remove.")
                    continue
                file_text = path.read_text(encoding="utf-8")
                status = _agentsmd_block_state(file_text, skill_name)
                if status == "absent":
                    warnings.append(f"agentsmd/{skill_name}: not installed, nothing to remove.")
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
                else:
                    new_file = _agentsmd_remove_block(file_text, skill_name)
                # Never delete AGENTS.md itself, even if this empties it --
                # that's a judgment call for the human, not this command.
                atomic_write_text(path, new_file)
                removed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
                any_stub_removed = True
                continue

            path = _resolve_path(provider_name, skill_name, target_dir, scope)
            if not path.exists():
                warnings.append(f"{provider_name}/{skill_name}: not installed, nothing to remove.")
                continue
            existing = path.read_text(encoding="utf-8")
            status = check_drift(existing)
            if _blocks_write(status, force):
                skipped.append({"provider": provider_name, "skill": skill_name, "file": str(path), "reason": status})
                continue
            path.unlink(missing_ok=True)
            removed.append({"provider": provider_name, "skill": skill_name, "file": str(path)})
            if spec["mode"] in ("stub", "stub_block"):
                any_stub_removed = True

        if any_stub_removed:
            still_referenced = _other_stub_providers_reference(target_dir, skill_name, scope, None, provider_names)
            if not still_referenced:
                shared_path = _shared_doc_path(target_dir, skill_name)
                if shared_path.exists():
                    shared_status = check_drift(shared_path.read_text(encoding="utf-8"))
                    if _blocks_write(shared_status, force):
                        skipped.append(
                            {"provider": "shared-doc", "skill": skill_name, "file": str(shared_path), "reason": shared_status}
                        )
                    else:
                        shared_path.unlink(missing_ok=True)
                        removed.append({"provider": "shared-doc", "skill": skill_name, "file": str(shared_path)})

    return {"removed": removed, "skipped": skipped, "warnings": warnings}


def list_installed(target_dir, providers, skills):
    provider_names = _expand(providers, PROVIDERS)
    skill_names = _expand(skills, resources.SKILL_NAMES)
    rows = []

    for skill_name in skill_names:
        for provider_name in provider_names:
            spec = PROVIDERS[provider_name]
            scopes = ("project", "global") if provider_name == "claude" else ("project",)
            for scope in scopes:
                if scope == "global" and spec["global_path"] is None:
                    continue
                path = _resolve_path(provider_name, skill_name, target_dir, scope)
                if provider_name == "agentsmd":
                    file_text = path.read_text(encoding="utf-8") if path.exists() else ""
                    status = _agentsmd_block_state(file_text, skill_name)
                    installed_flag = status != "absent"
                    # "foreign"/"malformed" count as drifted here too: all mean
                    # install/remove would refuse to touch this path without
                    # --force, which is the one thing this boolean needs to tell
                    # the caller.
                    drifted = None if not installed_flag else status in ("drifted", "foreign", "malformed")
                else:
                    existing = path.read_text(encoding="utf-8") if path.exists() else None
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

    return {"skills": rows, "warnings": []}
