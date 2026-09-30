"""Decision-log entries (ADR0003V01): the lighter-weight sibling of a
repository's formal ADRs, for an event worth recording that is not
itself an architectural decision. This module owns only the mechanical
part of that record -- filename construction, structured-line
formatting, and index regeneration -- never the judgment (classification,
wording) that produces the values passed in; see
doc/decision-log-workflow.md for that authoring process.

Filename convention, date first:
{ISO date}--{classification}--{scope}--{slug}.md.

ADR0007V01: the decision-log directory is `config.folderlog`, scanned
recursively. It defaults to 'decision-log' next to folderadr when the
config has no folderlog (core/config.py's parse_repo_config).
"""

import os
import re
from pathlib import Path
from urllib.parse import quote

from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.naming import reject_too_long_filename
from adrpy.core.header import read_header_lines
from adrpy.core.fs import scan_tree, written_by_someone_else
from adrpy.core.warnings import excluded_candidate_warning
from adrpy.core.security import resolve_within
from adrpy.core.text import parse_ascii_int

CLASSIFICATIONS = (
    "audit-finding",
    "retraction",
    "doc-drift",
    "accepted-divergence",
    "scope-note",
    "deferred",
    "risk-accepted",
    "investigation",
    "process-exception",
)

# audit-finding/doc-drift carry Front/Severity/Resolution/Round; deferred
# carries Reopen-when instead; every other classification carries neither.
STRUCTURED_CLASSIFICATIONS = frozenset({"audit-finding", "doc-drift"})
DEFERRED_CLASSIFICATION = "deferred"

SEVERITIES = ("Low", "Medium", "High")
RESOLUTIONS = ("Direct", "Escalated", "Retraction")

_KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

_FRONT_SEVERITY_RE = re.compile(
    r"^\*\*Front:\*\*\s*(.+?)\s*\|\s*\*\*Severity:\*\*\s*(.+?)"
    r"(?:\s*\|\s*\*\*Resolution:\*\*\s*(.+?))?"
    r"(?:\s*\|\s*\*\*Round:\*\*\s*(.+?))?\s*$"
)
_REOPEN_WHEN_RE = re.compile(r"^\*\*Reopen-when:\*\*\s*(.+?)\s*$")

_INDEX_FILENAME = "INDEX.md"
_NON_ENTRY_FILES = {_INDEX_FILENAME, "CYCLES.md"}
# The line that tells the generated index from a file of the user's.
_INDEX_MARK = "Generated -- do not edit by hand"
# Said with every refusal over a file that is not an entry, so an agent
# does not silently move the user's note away to get its entry written.
_USERS_FILE = (
    " It was not written by adrpy: it is the user's file -- ask where it belongs before moving it, "
    "and never delete it."
)


def decision_log_dir_for(target, config):
    """ADR0007V01: resolved from `config.folderlog`, the same way
    `folderadr` is resolved everywhere else (`resolve_within`)."""
    return resolve_within(target, config.folderlog)


def validate_classification(value):
    if value not in CLASSIFICATIONS:
        raise CommandError(
            FailureCodes.LOG_CLASSIFICATION_INVALID,
            f"'{value}' is not a recognized classification. Must be one of: {', '.join(CLASSIFICATIONS)}.",
            data={"classification": value},
        )


def validate_slug(value):
    if not _KEBAB_RE.match(value):
        raise CommandError(
            FailureCodes.LOG_SLUG_INVALID,
            f"'{value}' is not valid kebab-case: lowercase letters/digits only, single hyphens between "
            "words, no leading/trailing/double hyphens.",
            data={"slug": value},
        )


def validate_scope(value):
    """Stricter than `reject_embedded_delimiter` alone: `scope` becomes a
    literal `--`-delimited segment of the entry's own filename, so `/`,
    `\\`, and an embedded `--` are not just cosmetically wrong -- `/`/`\\`
    would be read as real path separators once joined onto the decision-log
    directory, and `--` would desynchronize every consumer that splits the
    filename on that delimiter (`_parse_entry` below)."""
    if not _KEBAB_RE.match(value):
        raise CommandError(
            FailureCodes.LOG_SCOPE_INVALID,
            f"'{value}' is not valid kebab-case: lowercase letters/digits only, single hyphens between "
            "words, no leading/trailing/double hyphens, no '/' or '\\'.",
            data={"scope": value},
        )


def validate_severity(value):
    if value not in SEVERITIES:
        raise CommandError(
            FailureCodes.LOG_SEVERITY_INVALID,
            f"'{value}' is not a recognized severity. Must be one of: {', '.join(SEVERITIES)}.",
            data={"severity": value},
        )


def validate_resolution(value):
    if value not in RESOLUTIONS:
        raise CommandError(
            FailureCodes.LOG_RESOLUTION_INVALID,
            f"'{value}' is not a recognized resolution. Must be one of: {', '.join(RESOLUTIONS)}.",
            data={"resolution": value},
        )


def parse_round(value):
    """A caller-supplied --round must be a positive integer -- this is a
    malformed-argument concern (usage-error), distinct from whether that
    integer is actually large enough (log-round-too-low, a domain
    decision checked separately once the current max is known)."""
    try:
        parsed = parse_ascii_int(value)
    except (AttributeError, TypeError, ValueError):
        parsed = None
    if parsed is None or parsed < 1:
        raise CommandError(
            FailureCodes.LOG_ROUND_INVALID, f"'{value}' is not a positive integer.", data={"round": value}
        )
    return parsed


def validate_round_not_regressing(round_, current_max):
    """Round is a single, project-wide, ever-increasing integer that never
    resets: reusing the current max (the common case: another finding in
    the same already-open round) is fine; anything below it is refused."""
    if round_ < current_max:
        raise CommandError(
            FailureCodes.LOG_ROUND_TOO_LOW,
            f"--round {round_} is lower than the highest Round already recorded ({current_max}); "
            "Round never decreases. Omit --round to continue with the next one, or pass "
            f"--round {current_max} to reuse the round already in progress.",
            data={"round": round_, "current_max": current_max},
        )


def build_filename(refdate, classification, scope, slug):
    filename = f"{refdate.isoformat()}--{classification}--{scope}--{slug}.md"
    reject_too_long_filename(filename, "shorten --scope or --slug")
    return filename


def build_entry_content(summary, body, *, front=None, severity=None, resolution=None, round_=None, reopen_when=None):
    lines = [f"# {summary}", ""]
    if front is not None:
        lines.append(f"**Front:** {front} | **Severity:** {severity} | **Resolution:** {resolution} | **Round:** {round_}")
        lines.append("")
    elif reopen_when is not None:
        lines.append(f"**Reopen-when:** {reopen_when}")
        lines.append("")
    lines.append(body)
    lines.append("")
    return "\n".join(lines)


def _parse_entry(path, name):
    """`name` is the entry's path in the log folder, which may have
    subfolders (ADR0007V01): what its link and every message name."""
    try:
        date, classification, scope, _slug = path.stem.split("--", 3)
    except ValueError as error:
        raise CommandError(
            FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
            f"{name} does not match the expected "
            "{ISO date}--{classification}--{scope}--{slug}.md shape -- cannot safely compute the next "
            "Round or regenerate INDEX.md while this file is present." + _USERS_FILE,
            data={"file": name},
        ) from error
    if classification not in CLASSIFICATIONS:
        # Same failure as an unparseable filename shape, not a softer one:
        # with an unrecognized classification (e.g. a typo'd
        # "audit-findings") the structured-line gate below can't know
        # whether to look for Front/Severity/Round or Reopen-when, and
        # would treat the entry as carrying neither -- risking a
        # duplicate Round.
        raise CommandError(
            FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
            f"{name} has an unrecognized classification ('{classification}') -- cannot safely "
            "compute the next Round or regenerate INDEX.md while this file is present." + _USERS_FILE,
            data={"file": name},
        )
    # Bounded read: only lines[0] (heading) and lines[1:5] are used, and
    # no field written via `log` has a length limit, so one oversized
    # --body would otherwise be read in full by every later `log` call.
    lines = read_header_lines(path, count=5)
    if not lines:
        # Fails closed like the two guards above: an empty (or otherwise
        # heading-less) file is just as unsafe to guess past.
        raise CommandError(
            FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
            f"{name} has no content -- cannot safely compute the next Round or regenerate "
            "INDEX.md while this file is present." + _USERS_FILE,
            data={"file": name},
        )
    heading = lines[0].lstrip("#").strip()
    front, severity, resolution, round_, reopen_when = "", "", "", "", ""
    # Gated by the entry's OWN classification (from its filename), not
    # attempted unconditionally -- otherwise a non-structured entry whose
    # free-form body happens to start with "**Front:** ... | **Severity:**
    # ..."-shaped prose gets silently misread as a real structured line,
    # skewing next_round's own count.
    if classification in STRUCTURED_CLASSIFICATIONS:
        for line in lines[1:5]:
            match = _FRONT_SEVERITY_RE.match(line)
            if match:
                front, severity = match.group(1), match.group(2)
                resolution, round_ = match.group(3) or "", match.group(4) or ""
                break
    elif classification == DEFERRED_CLASSIFICATION:
        for line in lines[1:5]:
            match = _REOPEN_WHEN_RE.match(line)
            if match:
                reopen_when = match.group(1)
                break
    return {
        "path": name,
        "classification": classification,
        "date": date,
        "scope": scope,
        "summary": heading,
        "front": front,
        "severity": severity,
        "resolution": resolution,
        "round": round_,
        "reopen_when": reopen_when,
    }


def _existing_entries(decision_log_dir, *, warnings=None):
    """ADR0007V01: recursive, since `folderlog` is independently placeable
    and so not flat by construction. Walked with core/fs.scan_tree, the
    decisions folder's own scan. Fails closed on an unreadable
    subdirectory instead of silently under-reporting -- every caller makes
    a safety decision from the result (Round allocation, index
    correctness, the change guard below). A file
    whose real path escapes the folder (through a junction) is excluded
    and reported in `warnings`, once per command."""
    decision_log_dir = Path(decision_log_dir)
    if not decision_log_dir.is_dir():
        return []
    scan = scan_tree(decision_log_dir)
    if warnings is not None:
        warning = excluded_candidate_warning(list(scan.excluded))
        if warning and warning not in warnings:
            warnings.append(warning)
    unreadable = list(scan.unreadable)
    if unreadable:
        raise CommandError(
            FailureCodes.LOG_SCAN_INCOMPLETE,
            f"Cannot safely scan {decision_log_dir}: {len(unreadable)} subdirectory/subdirectories could "
            "not be scanned (permission denied or similar).",
            data={"folder": str(decision_log_dir), "unreadable": unreadable},
            warnings=warnings,
        )
    return [_parse_entry(path, path.relative_to(decision_log_dir).as_posix()) for path in _entry_candidates(scan)]


def _entry_candidates(scan):
    """The files of `scan` that must each be an entry: every `.md` but
    the log's own INDEX.md and CYCLES.md, their names compared as the file
    system compares them, sorted."""
    own = {os.path.normcase(name) for name in _NON_ENTRY_FILES}
    return [path for path in sorted(scan.markdown) if os.path.normcase(path.name) not in own]


def unrecognized_log_files_warning(target, config):
    """The warning for the files under `config.folderlog` that are not
    decision-log entries -- the ones `log` refuses to write past
    (log-directory-contains-unrecognized-file, the same _parse_entry
    reading), e.g. a note moved into the log. None when there are none,
    when folderlog does not exist, or when it cannot be resolved inside
    the repository. Never raises for what it cannot read: a subdirectory
    or file that cannot be read is left out, not reported as a stray."""
    try:
        decision_log_dir = decision_log_dir_for(target, config)
    except CommandError:
        return None
    if not decision_log_dir.is_dir():
        return None
    names = []
    for path in _entry_candidates(scan_tree(decision_log_dir)):
        try:
            _parse_entry(path, path.relative_to(decision_log_dir).as_posix())
        except CommandError as error:
            if error.code != FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE:
                raise
            names.append(path.relative_to(decision_log_dir).as_posix())
        except OSError:
            continue
    if not names:
        return None
    return (
        f"{len(names)} file(s) in {config.folderlog} are not decision-log entries: {', '.join(names)}. "
        "adrpy did not write them, so they are the user's files: ask where they belong before moving "
        "any, and never delete one (an entry whose name is wrong is renamed to "
        "{ISO date}--{classification}--{scope}--{slug}.md instead). `adrpy log` refuses to write an entry "
        "while any of them is there (log-directory-contains-unrecognized-file)."
    )


def check_entries(decision_log_dir, *, warnings=None):
    """Raises what regenerate_index would raise for the files under
    `decision_log_dir` (log-directory-contains-unrecognized-file,
    log-scan-incomplete), without writing anything -- `log` runs it
    before writing an entry of any classification."""
    _existing_entries(decision_log_dir, warnings=warnings)


def reject_folderlog_change_if_entries_exist(old_log_dir, old_folderlog, new_folderlog, *, target, warnings=None):
    """The folderlog counterpart to the folderadr check of core/lifecycle.py's
    validate_config_change (ADR0007V01), which calls it -- changing
    folderlog on a repository that already has decision-log entries makes
    every one of them invisible at their old, still-real path. Unlike the
    folderadr guard, no separate scan-incomplete code is needed:
    _existing_entries already fails closed on an unreadable subdirectory
    (LOG_SCAN_INCOMPLETE) or an unrecognized filename
    (LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE), and those errors
    propagate through this function unchanged.

    Also guards the opposite direction, as the folderadr guard does
    (ADR0004V02): `new_folderlog` may already hold unrelated content that
    would silently become recognized decision-log history (round
    allocation, INDEX.md) the moment anything scans it. Skipped when the
    new directory does not exist yet."""
    if new_folderlog == old_folderlog:
        return
    existing = _existing_entries(old_log_dir, warnings=warnings)
    if existing:
        raise CommandError(
            FailureCodes.FOLDERLOG_CHANGE_BLOCKED_BY_EXISTING_ENTRIES,
            f"Cannot change folderlog from '{old_folderlog}' to '{new_folderlog}': "
            f"{len(existing)} existing decision-log entry/entries under '{old_folderlog}' would become "
            "invisible.",
            data={"folderlog": old_folderlog, "existing_entries": len(existing)},
            warnings=warnings,
        )

    new_log_dir = resolve_within(target, new_folderlog)
    if new_log_dir.is_dir():
        adopted = _existing_entries(new_log_dir, warnings=warnings)
        if adopted:
            raise CommandError(
                FailureCodes.FOLDERLOG_CHANGE_WOULD_ADOPT_UNRELATED_FILES,
                f"Cannot change folderlog to '{new_folderlog}': {len(adopted)} file(s) already there would "
                "silently become recognized decision-log entries.",
                data={"folderlog": new_folderlog, "adopted_files": sorted(entry["path"] for entry in adopted)},
                warnings=warnings,
            )


def max_existing_round(decision_log_dir, *, warnings=None):
    """0 if no audit-finding/doc-drift entry carries a Round yet, else the
    highest one found -- what both next_round's default and an explicit
    --round's lower-bound check are built on.

    Fails closed (rather than silently skipping) on a structured entry
    whose Round is missing or not a positive integer -- e.g. a hand-written
    entry with no structured line at all, or one written "5 (tentative)":
    skipping it would under-report the real max, and a later call could
    allocate a Round that duplicates the one on that file."""
    rounds = []
    for entry in _existing_entries(decision_log_dir, warnings=warnings):
        if entry["classification"] not in STRUCTURED_CLASSIFICATIONS:
            continue
        try:
            rounds.append(parse_ascii_int(entry["round"]))
            if rounds[-1] < 1:
                raise ValueError(entry["round"])
        except (AttributeError, TypeError, ValueError) as error:
            raise CommandError(
                FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
                f"{entry['path']} is classified '{entry['classification']}' but its Round "
                f"({entry['round']!r}) is missing or not a positive integer -- cannot safely compute "
                "the next Round while this file is present.",
                data={"file": entry["path"]},
            ) from error
    return max(rounds, default=0)


def next_round(decision_log_dir, *, warnings=None):
    """The default Round when none is given explicitly: always the start
    of a NEW round (max existing + 1) -- the same class of allocation as
    an ADR's own next_number. Reusing an already-open round instead
    requires passing --round explicitly (ADR0003V01); this function is
    never the only way to pick a Round, only the safe default."""
    return max_existing_round(decision_log_dir, warnings=warnings) + 1


def _cell(text):
    """A table cell from a hand-written entry's text: a lone surrogate
    (valid in an NTFS name, not in UTF-8) shown as U+FFFD, so one odd name
    cannot stop the page, and `|` escaped, so the row keeps its columns
    (a backslash is left as written: a code span shows it as is)."""
    text = str(text).encode("utf-8", "surrogatepass").decode("utf-8", "replace")
    return text.replace("|", "\\|")


def previous_index_warning(old_dir, new_dir, warnings):
    """After a folderlog change, names the generated index the previous
    folder still holds (never deleted: it is the user's call). Never
    raises, not even Ctrl+C: the config is already written. The folders
    are compared as the file system resolves them, so the same folder
    spelled another way (`doc/../doc/log`, a link to it) is no previous one."""
    old_index = Path(old_dir) / _INDEX_FILENAME
    try:
        same = os.path.normcase(os.path.realpath(old_dir)) == os.path.normcase(os.path.realpath(new_dir))
        if not same and old_index.is_file() and not written_by_someone_else(old_index, _INDEX_MARK):
            warnings.append(f"{old_index} is the index of the previous decision-log folder: delete it if it is no "
                            "longer needed.")
    except KeyboardInterrupt:
        warnings.append(f"{old_index} was not looked at: interrupted (Ctrl+C). The config is written.")
    except OSError:
        pass


def regenerate_index(decision_log_dir, *, warnings=None):
    """Rebuilds INDEX.md from the entry files themselves -- always
    generated, never hand-maintained prose (see that file's own header).
    Returns the number of entries indexed. An INDEX.md without _INDEX_MARK
    is the user's: left as it is, with a warning when `warnings` is given."""
    decision_log_dir = Path(decision_log_dir)
    index = decision_log_dir / _INDEX_FILENAME
    if written_by_someone_else(index, _INDEX_MARK):
        if warnings is not None:
            warnings.append(
                f"{index} was not written by adrpy (or cannot be read), so it is left as it is and the decision-log index is "
                "not written: rename or move that file to have the index."
            )
        return 0
    entries = _existing_entries(decision_log_dir, warnings=warnings)
    entries.sort(key=lambda entry: (entry["date"], entry["classification"], entry["scope"]))

    lines = [
        "# Decision log index",
        "",
        f"{_INDEX_MARK} (see [the decision-log workflow](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/decision-log-workflow.md)).",
        "",
        "## How entries are named",
        "",
        "Every file follows `{ISO date}--{classification}--{scope}--{slug}.md` "
        "(date first so a raw directory listing already sorts chronologically, "
        "matching this generated index's own sort order):",
        "",
        "- **date** -- ISO date the entry was written, not necessarily when the "
        "underlying event happened.",
        "- **classification** -- a closed vocabulary: `audit-finding` (a bug found "
        "and fixed, or a review pass's closure claim), `retraction` (a prior verdict "
        "or decision that didn't hold), `doc-drift` (a durable doc describing "
        "something that stopped being true), `accepted-divergence` (a confirmed "
        "difference from some external reference, not an architecture change), "
        "`scope-note` (a clarification of an existing decision's boundary), "
        "`deferred` (postponed, with a named reopening condition), `risk-accepted` "
        "(a known gap left unfixed on purpose, no reopening condition), "
        "`investigation` (a suspicion checked and found not to hold), or "
        "`process-exception` (a one-off deviation from standing process).",
        "- **scope** -- the module/command/concern the entry is about, reusing the "
        "project's own vocabulary (e.g. `io`, `config`, `cli`).",
        "- **slug** -- a few kebab-case words identifying this specific entry; what "
        "actually guarantees the filename is unique, since classification+date+scope "
        "alone commonly repeat.",
        "",
        "For `audit-finding`/`doc-drift` entries specifically, the four extra columns "
        "below come from a structured line inside the entry itself (`**Front:** ... | "
        "**Severity:** ... | **Resolution:** ... | **Round:** ...`), used by the "
        "`pre-release-audit` skill's calibration step -- blank for every other "
        "classification, which doesn't carry that line:",
        "",
        "- **Front** -- which review angle found it (free text -- may still mention "
        "the round narratively, but **Round** below is the authoritative, "
        "mechanically-parseable value).",
        "- **Severity** -- Low / Medium / High.",
        "- **Resolution** -- `Direct` (followed an already-established pattern, no "
        "design choice needed), `Escalated` (a real trade-off, presented as options "
        "and chosen by the project owner before implementation), or `Retraction` "
        "(reverses a previously confirmed decision that didn't hold).",
        "- **Round** -- a single, project-wide, ever-increasing integer identifying "
        "the pre-release-audit round this entry belongs to. Never resets. Reusing the "
        "same Round across several entries in the same round is normal and expected "
        "(`adrpy log --round N`); omitting `--round` always starts a new one. A "
        "human-friendly **Cycle** name grouping a range of rounds, when one is "
        "warranted, lives separately in this folder's `CYCLES.md`, if present -- "
        "never repeated on individual entries, and only ever assigned in hindsight "
        "once a cycle's own boundary is visible (see that file for the naming rule).",
        "",
        "`deferred` entries carry their own, different structured line instead -- "
        "`**Reopen-when:** ...` -- the reopening condition every `deferred` entry "
        "already has to name, structured so it can be checked mechanically without "
        "re-reading each entry's own prose.",
        "",
        "| Date | Classification | Scope | Front | Severity | Resolution | Round | Reopen-when | Summary | File |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in entries:
        cells = [_cell(entry[key]) for key in ("date", "classification", "scope", "front", "severity",
                                                "resolution", "round", "reopen_when", "summary")]
        link_text = _cell(str(entry["path"]).replace("\\", "\\\\")).replace("[", "\\[").replace("]", "\\]")
        cells.append(f"[{link_text}]({quote(entry['path'], safe='/-_.,;', errors='surrogatepass')})")
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")

    # Atomic: a plain write_text() truncates on open, so a concurrent
    # reader (or a process that dies mid-write) could see or leave an
    # empty INDEX.md. atomic_write_text writes THIS host's os.linesep.
    atomic_write_text(index, "\n".join(lines))
    return len(entries)
