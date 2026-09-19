"""Decision-log entries (ADR003V01): the lighter-weight sibling of a
repository's formal ADRs, for an event worth recording that is not
itself an architectural decision. This module owns only the mechanical
part of that record -- filename construction, structured-line
formatting, and index regeneration -- never the judgment (classification,
wording) that produces the values passed in; see
doc/decision-log-workflow.md for that authoring process.

Filename convention is this project's own, date-first, established
independently of ADR003 (see doc/decision-log/INDEX.md's own header and
every real entry): {ISO date}--{classification}--{scope}--{slug}.md,
in a directory sibling to the repository's decisions folder, never
nested inside it -- the same structural reasoning that excludes the
repository lock marker file from every decisions-folder scan.
"""

import re
from pathlib import Path

from adrpy.core.atomic_write import atomic_write_bytes
from adrpy.core.errors import CommandError

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


def decision_log_dir_for(decisions_folder):
    return Path(decisions_folder).parent / "decision-log"


def validate_classification(value):
    if value not in CLASSIFICATIONS:
        raise CommandError(
            "log-classification-invalid",
            f"'{value}' is not a recognized classification. Must be one of: {', '.join(CLASSIFICATIONS)}.",
            data={"classification": value},
        )


def validate_slug(value):
    if not _KEBAB_RE.match(value):
        raise CommandError(
            "log-slug-invalid",
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
            "log-scope-invalid",
            f"'{value}' is not valid kebab-case: lowercase letters/digits only, single hyphens between "
            "words, no leading/trailing/double hyphens, no '/' or '\\'.",
            data={"scope": value},
        )


def validate_severity(value):
    if value not in SEVERITIES:
        raise CommandError(
            "log-severity-invalid",
            f"'{value}' is not a recognized severity. Must be one of: {', '.join(SEVERITIES)}.",
            data={"severity": value},
        )


def validate_resolution(value):
    if value not in RESOLUTIONS:
        raise CommandError(
            "log-resolution-invalid",
            f"'{value}' is not a recognized resolution. Must be one of: {', '.join(RESOLUTIONS)}.",
            data={"resolution": value},
        )


def parse_round(value):
    """A caller-supplied --round must be a positive integer -- this is a
    malformed-argument concern (usage-error), distinct from whether that
    integer is actually large enough (log-round-too-low, a domain
    decision checked separately once the current max is known)."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = None
    if parsed is None or parsed < 1:
        raise CommandError(
            "log-round-invalid", f"'{value}' is not a positive integer.", data={"round": value}
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
            "log-round-too-low",
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
            "log-directory-contains-unrecognized-file",
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
            "log-directory-contains-unrecognized-file",
            f"{path.name} has an unrecognized classification ('{classification}') -- cannot safely "
            "compute the next Round or regenerate INDEX.md while this file is present.",
            data={"file": path.name},
        )
    lines = path.read_text(encoding="utf-8").splitlines()
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


def _existing_entries(decision_log_dir):
    decision_log_dir = Path(decision_log_dir)
    if not decision_log_dir.is_dir():
        return []
    return [
        _parse_entry(path)
        for path in sorted(decision_log_dir.glob("*.md"))
        if path.name not in _NON_ENTRY_FILES
    ]


def max_existing_round(decision_log_dir):
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
    for entry in _existing_entries(decision_log_dir):
        if entry["classification"] not in STRUCTURED_CLASSIFICATIONS:
            continue
        try:
            rounds.append(int(entry["round"]))
        except (TypeError, ValueError) as error:
            raise CommandError(
                "log-directory-contains-unrecognized-file",
                f"{entry['path']} is classified '{entry['classification']}' but its Round "
                f"({entry['round']!r}) is missing or not a plain integer -- cannot safely compute "
                "the next Round while this file is present.",
                data={"file": entry["path"]},
            ) from error
    return max(rounds, default=0)


def next_round(decision_log_dir):
    """The default Round when none is given explicitly: always the start
    of a NEW round (max existing + 1) -- the same class of allocation as
    an ADR's own next_number. Reusing an already-open round instead
    requires passing --round explicitly (ADR003V01); this function is
    never the only way to pick a Round, only the safe default."""
    return max_existing_round(decision_log_dir) + 1


def regenerate_index(decision_log_dir):
    """Rebuilds INDEX.md from the entry files themselves -- always
    generated, never hand-maintained prose (see that file's own header).
    Returns the number of entries indexed."""
    decision_log_dir = Path(decision_log_dir)
    entries = _existing_entries(decision_log_dir)
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
    # disk -- an empty INDEX.md. atomic_write_bytes (not atomic_write_text)
    # deliberately skips newline normalization, matching this function's own
    # explicit LF-only convention regardless of host OS.
    atomic_write_bytes(decision_log_dir / _INDEX_FILENAME, "\n".join(lines).encode("utf-8"))
    return len(entries)
