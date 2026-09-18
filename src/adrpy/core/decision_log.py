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

_SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

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
    if not _SLUG_RE.match(value):
        raise CommandError(
            "log-slug-invalid",
            f"'{value}' is not valid kebab-case: lowercase letters/digits only, single hyphens between "
            "words, no leading/trailing/double hyphens.",
            data={"slug": value},
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
    date, classification, scope, _slug = path.stem.split("--", 3)
    lines = path.read_text(encoding="utf-8").splitlines()
    heading = lines[0].lstrip("#").strip()
    front, severity, resolution, round_, reopen_when = "", "", "", "", ""
    for line in lines[1:5]:
        match = _FRONT_SEVERITY_RE.match(line)
        if match:
            front, severity = match.group(1), match.group(2)
            resolution, round_ = match.group(3) or "", match.group(4) or ""
            break
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


def next_round(decision_log_dir):
    """1 if no audit-finding/doc-drift entry carries a Round yet, else
    max+1 -- the same class of allocation as an ADR's own next_number,
    scoped to this closed pair of classifications (ADR003V01)."""
    rounds = []
    for entry in _existing_entries(decision_log_dir):
        if entry["round"]:
            try:
                rounds.append(int(entry["round"]))
            except ValueError:
                continue
    return max(rounds, default=0) + 1


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
        "Generated by `scripts/generate_decision_log_index.py` -- do not edit by hand.",
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
        "the pre-release-audit round this entry belongs to. Never resets. A "
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

    (decision_log_dir / _INDEX_FILENAME).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return len(entries)
