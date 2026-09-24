"""Decision-log entries (ADR003V01): the lighter-weight sibling of a
repository's formal ADRs, for an event worth recording that is not
itself an architectural decision. This module owns only the mechanical
part of that record -- filename construction, structured-line
formatting, and index regeneration -- never the judgment (classification,
wording) that produces the values passed in; see
doc/decision-log-workflow.md for that authoring process.

Filename convention is this project's own, date-first, established
independently of ADR003 (see doc/decision-log/INDEX.md's own header and
every real entry): {ISO date}--{classification}--{scope}--{slug}.md.

ADR007V01 (superseding ADR003V01's own driver on this point): the
decision-log directory lives at `config.folderlog`, an independently
configurable, recursively-scanned field -- no longer a fixed, non-
recursive sibling of `folderadr`. Defaults to that exact sibling
location ('decision-log' next to folderadr) when a repository's own
config predates this field (see core/config.py's own parse_repo_config).
"""

import re
from pathlib import Path

from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.header import read_header_lines
from adrpy.core.security import find_unreadable_subdirectories, resolve_within
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


def decision_log_dir_for(target, config):
    """ADR007V01: resolved from `config.folderlog`, the same way
    `folderadr` itself is resolved everywhere else (`resolve_within`) --
    no longer derived from `folderadr`'s own path."""
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
    filename on that delimiter (`_parse_entry` below, and
    scripts/generate_decision_log_index.py's own predecessor logic).
    Real scope values already in this project's own decision log (`lock`,
    `config`, `install-config`, ...) are already kebab-case, so this is not
    a new constraint in practice, only one now actually enforced."""
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
    """Round is a single, project-wide, ever-increasing integer (never
    resets, per doc/decision-log/INDEX.md's own header) -- reusing the
    current max (the common case: another finding in the same
    already-open round) is fine; anything below it would violate that
    invariant outright."""
    if round_ < current_max:
        raise CommandError(
            FailureCodes.LOG_ROUND_TOO_LOW,
            f"--round {round_} is lower than the highest Round already recorded ({current_max}); "
            "Round never decreases. Omit --round to continue with the next one, or pass "
            f"--round {current_max} to reuse the round already in progress.",
            data={"round": round_, "current_max": current_max},
        )


def build_filename(refdate, classification, scope, slug):
    return f"{refdate.isoformat()}--{classification}--{scope}--{slug}.md"


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


def _parse_entry(path):
    try:
        date, classification, scope, _slug = path.stem.split("--", 3)
    except ValueError as error:
        raise CommandError(
            FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
            f"{path.name} does not match the expected "
            "{ISO date}--{classification}--{scope}--{slug}.md shape -- cannot safely compute the next "
            "Round or regenerate INDEX.md while this file is present.",
            data={"file": path.name},
        ) from error
    if classification not in CLASSIFICATIONS:
        # Same failure as an unparseable filename shape, not a softer one:
        # an unrecognized classification means the structured-line gate
        # below can't know whether to look for Front/Severity/Round or
        # Reopen-when, so it would otherwise silently treat the entry as
        # carrying neither -- reopening the exact duplicate-Round risk
        # this gate exists to close, just via a typo'd classification
        # (e.g. "audit-findings") instead of a coincidentally-structured
        # non-structured entry.
        raise CommandError(
            FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
            f"{path.name} has an unrecognized classification ('{classification}') -- cannot safely "
            "compute the next Round or regenerate INDEX.md while this file is present.",
            data={"file": path.name},
        )
    # Reading the ENTIRE entry file (path.read_text().splitlines()) would
    # be wasteful -- only lines[0] (heading) and, for a structured
    # classification, lines[1:5] are ever used. No field written via
    # `log` has a length limit, so a single oversized --body persisted
    # once would make every future `log` call re-pay the cost of reading
    # it in full, for every entry in the directory, on every
    # classification. Uses the same bounded read every scan elsewhere in
    # this codebase already relies on for exactly this reason
    # (core/lifecycle.py's own header reads).
    lines = read_header_lines(path, count=5)
    if not lines:
        # Same fail-closed treatment as an unparseable filename shape or
        # an unrecognized classification above -- an empty (or otherwise
        # heading-less) file is just as unsafe to guess past, the exact
        # bug class this function's other two guards already exist to
        # close.
        raise CommandError(
            FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
            f"{path.name} has no content -- cannot safely compute the next Round or regenerate "
            "INDEX.md while this file is present.",
            data={"file": path.name},
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
        "path": path.name,
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
    """ADR007V01: recursive (`rglob`, matching `folderadr`'s own scan
    convention), now that `folderlog` is independently placeable and no
    longer guaranteed flat by construction. Fails closed on an unreadable
    subdirectory instead of silently under-reporting -- every real caller
    of this function makes a safety decision from the result (Round
    allocation, index correctness, the change guard below), the same
    reasoning core/lifecycle.py's scan_decisions applies with
    strict=True; unlike that function, this one has no read-only/warn-
    only caller to also support, so it always fails closed."""
    decision_log_dir = Path(decision_log_dir)
    if not decision_log_dir.is_dir():
        return []
    unreadable = find_unreadable_subdirectories(decision_log_dir)
    if unreadable:
        raise CommandError(
            FailureCodes.LOG_SCAN_INCOMPLETE,
            f"Cannot safely scan {decision_log_dir}: {len(unreadable)} subdirectory/subdirectories could "
            "not be scanned (permission denied or similar).",
            data={"folder": str(decision_log_dir), "unreadable": unreadable},
            warnings=warnings,
        )
    return [
        _parse_entry(path)
        for path in sorted(decision_log_dir.rglob("*.md"))
        if path.name not in _NON_ENTRY_FILES
    ]


def reject_folderlog_change_if_entries_exist(old_log_dir, old_folderlog, new_folderlog, *, target, warnings=None):
    """The folderlog counterpart to core/lifecycle.py's
    reject_folderadr_change_if_decisions_exist (ADR007V01) -- changing
    folderlog on a repository that already has decision-log entries makes
    every one of them invisible at their old, still-real path. Unlike the
    folderadr guard, no separate scan-incomplete code is needed here:
    _existing_entries above already fails closed on an unreadable
    subdirectory (LOG_SCAN_INCOMPLETE) or an unrecognized filename
    (LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE) on its own, and those
    errors propagate through this function unchanged -- exactly the
    fail-closed behavior the folderadr guard's own separate code exists
    to provide there.

    Also guards the opposite direction, the same adoption hazard
    ADR004V02/the folderadr guard already close: `new_folderlog` may
    already hold unrelated content that would silently become
    recognized decision-log history (round allocation, INDEX.md) the
    moment anything scans it. Skipped entirely when the new directory
    does not exist yet."""
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
    highest one found -- the single source of truth both next_round's own
    default and an explicit --round's own lower-bound check are built on.

    Fails closed (rather than silently skipping) on a structured entry
    whose Round is missing or not a plain integer -- e.g. a hand-written
    entry with no structured line at all, or one written "5 (tentative)".
    Silently skipping it would let this function under-report the real
    max, and a later call could then allocate a Round that duplicates the
    one already on that file -- the same risk an unrecognized
    classification poses, just triggered by a malformed Round instead."""
    rounds = []
    for entry in _existing_entries(decision_log_dir, warnings=warnings):
        if entry["classification"] not in STRUCTURED_CLASSIFICATIONS:
            continue
        try:
            rounds.append(parse_ascii_int(entry["round"]))
        except (AttributeError, TypeError, ValueError) as error:
            raise CommandError(
                FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE,
                f"{entry['path']} is classified '{entry['classification']}' but its Round "
                f"({entry['round']!r}) is missing or not a plain integer -- cannot safely compute "
                "the next Round while this file is present.",
                data={"file": entry["path"]},
            ) from error
    return max(rounds, default=0)


def next_round(decision_log_dir, *, warnings=None):
    """The default Round when none is given explicitly: always the start
    of a NEW round (max existing + 1) -- the same class of allocation as
    an ADR's own next_number. Reusing an already-open round instead
    requires passing --round explicitly (ADR003V01); this function is
    never the only way to pick a Round, only the safe default."""
    return max_existing_round(decision_log_dir, warnings=warnings) + 1


def regenerate_index(decision_log_dir, *, warnings=None):
    """Rebuilds INDEX.md from the entry files themselves -- always
    generated, never hand-maintained prose (see that file's own header).
    Returns the number of entries indexed."""
    decision_log_dir = Path(decision_log_dir)
    entries = _existing_entries(decision_log_dir, warnings=warnings)
    entries.sort(key=lambda entry: (entry["date"], entry["classification"], entry["scope"]))

    lines = [
        "# Decision log index",
        "",
        "Generated -- do not edit by hand (see `doc/decision-log-workflow.md`).",
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
        "project's own vocabulary (e.g. `lock`, `config`, `cli`).",
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
        "warranted, lives separately in [`doc/decision-log/CYCLES.md`](CYCLES.md) -- "
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
        lines.append(
            f"| {entry['date']} | {entry['classification']} | {entry['scope']} "
            f"| {entry['front']} | {entry['severity']} | {entry['resolution']} | {entry['round']} "
            f"| {entry['reopen_when']} | {entry['summary']} | [{entry['path']}]({entry['path']}) |"
        )
    lines.append("")

    # Atomic, like every other writer in this project (core/atomic_write.py):
    # a plain write_text() truncates on open, so a concurrent reader (or a
    # process that dies mid-write) can observe -- or permanently leave on
    # disk -- an empty INDEX.md. atomic_write_text normalizes to THIS host's
    # own os.linesep, matching every other CRLF-on-Windows doc in this
    # project instead of a hardcoded LF regardless of host OS.
    atomic_write_text(decision_log_dir / _INDEX_FILENAME, "\n".join(lines))
    return len(entries)
