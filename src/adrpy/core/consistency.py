"""The repository model and its validator.

One scan of the decisions folder (core/fs.scan_tree) gives a `Decision`
for every file with an ADR name -- a `.md` whose name matches neither
naming scheme is not a decision and is ignored. Each decision's `state`
is derived once, from a closed set of status combinations (the ones the
tool itself writes, plus the migrated shapes). `check_repository`
returns the snapshot with every broken invariant it finds;
`validate_repository` raises repository-inconsistent when there is any.

The invariants, one error code each (HINTS has a repair hint per code):

- header: merge-conflict markers in the 12 header lines are reported
  first, and alone; then no-header (nothing like this tool's header) or
  invalid-header (it does not parse, the reason in `detail`), and
  invalid-status-combination (it parses, but the status cells are not
  in the closed set);
- numbering: no two files share (number, version, revision), a missing
  revision counting as 0;
- family (same number): at most one open Proposed (a migrated
  placeholder is not one), and it is the live member; at most one
  Superseded, and it is the live member; in the family of a Rejected
  successor, every member is Rejected;
- supersede: a Superseded decision points at a successor that exists,
  is not Rejected, and whose filename suffix names this decision; a
  successor that is not Rejected (suffix `<sep><sep>NNN` naming a lower
  number) has a predecessor pointing back at it; a predecessor has at
  most one successor that is not Rejected;
- scan: a directory or decision file that could not be read.

"Live" is family.locking_member's rule: the family's latest member,
newer members that are all Rejected not counting.
"""

from dataclasses import dataclass

from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.fs import scan_tree
from adrpy.core.family import is_successor, locking_member
from adrpy.core.header import describe_header_error, has_header_shape, parse_header, read_header_lines_with_report
from adrpy.core.naming import parse_any_filename
from adrpy.core.text import ascii_digits_int

PROPOSED = "proposed"
ACCEPTED = "accepted"
REJECTED = "rejected"
SUPERSEDED = "superseded"
PLACEHOLDER = "placeholder"

# (Created, Changed, Superseded) -> state. Created is always Proposed on
# a file the tool created; approve/reject fill Changed, supersede the
# Superseded cell (only after Accepted).
_CLOSED_SET = {
    ("Proposed", None, None): PROPOSED,
    ("Proposed", "Accepted", None): ACCEPTED,
    ("Proposed", "Rejected", None): REJECTED,
    ("Proposed", "Accepted", "Superseded"): SUPERSEDED,
}
# A migrated file (the `<!-- Migrated -->` marker) keeps Created blank:
# migrate writes a placeholder, and approve/reject/supersede act on it
# as on a Proposed one -- supersede also straight from the placeholder.
_MIGRATED_CLOSED_SET = {
    (None, None, None): PLACEHOLDER,
    (None, "Accepted", None): ACCEPTED,
    (None, "Rejected", None): REJECTED,
    (None, "Accepted", "Superseded"): SUPERSEDED,
    (None, None, "Superseded"): SUPERSEDED,
}

_CONFLICT_MARKERS = ("<<<<<<< ", ">>>>>>> ")

HINTS = {
    FailureCodes.MERGE_CONFLICT_MARKERS: (
        "The header holds git merge-conflict markers (<<<<<<<, =======, >>>>>>>). Resolve the conflict "
        "by hand, keeping one version of each of the 12 header lines, then run adrpy check again."
    ),
    FailureCodes.NO_HEADER: (
        "The file has an ADR name but no header. If it is a decision written before adopting the tool and "
        "no decision was created with the tool yet, run adrpy migrate (it runs only once, before any "
        "new; set migrationpattern with adrpy config first if the names need it). Otherwise migrate refuses: give it a header by hand (copy one from a decision the tool "
        "created), rename it so its name is not an ADR name, or remove it."
    ),
    FailureCodes.INVALID_HEADER: (
        "The header does not parse (detail names the reason). Repair it by hand, comparing it with the "
        "header of a decision the tool created, or restore it from git history."
    ),
    FailureCodes.INVALID_STATUS_COMBINATION: (
        "The Created/Changed/Superseded cells form a combination no command writes: Created is Proposed "
        "(blank only on a migrated file), Changed is blank, Accepted or Rejected, and Superseded is set "
        "only after Accepted (or on a migrated placeholder). Repair the cells by hand."
    ),
    FailureCodes.DUPLICATE_NUMBER: (
        "Two files have the same number, version and revision (a missing revision counts as 0), usually "
        "from merging two branches that each created one. Keep the number on one of them and give the "
        "other a free number: rename its file and move the references to it along -- the Superseded cell "
        "(': NNN') of the predecessor it supersedes, and the '<sep><sep>NNN' suffix in the filename of "
        "any successor that supersedes it."
    ),
    FailureCodes.PENDING_DUPLICATE: (
        "The family has more than one open Proposed decision (a migrated placeholder does not count). Keep "
        "one: approve or reject the others by hand in their Changed cell, or remove the files never meant "
        "to exist."
    ),
    FailureCodes.PENDING_NOT_LIVE: (
        "A Proposed decision is not the live member of its family: a newer member that is not Rejected "
        "(related_files) locks it. By hand (commands refuse this repository): set its Changed cell to "
        "Rejected or remove it, or set the newer member's Changed cell to Rejected."
    ),
    FailureCodes.SUPERSEDED_DUPLICATE: (
        "The family has more than one Superseded member; only the live one can be superseded. Keep the "
        "Superseded cell on the live member and clear it on the others (their successors then need "
        "their suffix or status repaired too)."
    ),
    FailureCodes.SUPERSEDED_NOT_LIVE: (
        "A Superseded decision is not the live member of its family: a newer member that is not Rejected "
        "(related_files) locks it. By hand (commands refuse this repository): move the Superseded cell to "
        "the live member, or set the newer member's Changed cell to Rejected."
    ),
    FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR: (
        "The Superseded cell (': NNN') points at no successor that exists, is not Rejected and names this "
        "decision in its '<sep><sep>NNN' filename suffix. Fix the cell's number, or clear the Superseded "
        "cell if the supersede never finished or its successor was rejected."
    ),
    FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR: (
        "A successor (its filename ends in '<sep><sep>NNN') that is not Rejected has no member of family "
        "NNN whose Superseded cell points back at it, usually a supersede (or a reject) that stopped "
        "halfway. By hand (commands refuse this repository): mark the live member of family NNN Superseded "
        "with ': <this number>', set this successor's Changed cell to Rejected, or remove it if it was "
        "just created from the template."
    ),
    FailureCodes.MULTIPLE_LIVE_SUCCESSORS: (
        "More than one successor that is not Rejected names the same predecessor. By hand (commands "
        "refuse this repository): keep the one the predecessor's Superseded cell points at, and set the "
        "others' Changed cell to Rejected or remove them."
    ),
    FailureCodes.REJECTED_SUCCESSOR_FAMILY_NOT_FINAL: (
        "A member of a Rejected successor's family (related_files) is not Rejected. A rejected successor "
        "ends its whole family. By hand (commands refuse this repository): set this member's Changed cell "
        "to Rejected, or remove it. The line continues by superseding the predecessor again."
    ),
    FailureCodes.SCAN_INCOMPLETE: (
        "A directory or decision file under the decisions folder could not be read (permission denied or "
        "similar), so the repository cannot be checked. Fix its permissions and run again."
    ),
}


@dataclass(frozen=True)
class Decision:
    """One file with an ADR name: its filename identity (`name`, a
    ParsedFileName, and `scheme`), its parsed header and its `state` --
    one of the module's state constants, or None when the header does not
    parse or its status cells are outside the closed set.
    `successor_ref` is the Superseded cell's number, for a Superseded
    decision whose cell holds plain digits. `encoding_repaired`: the
    header read needed a lossy decode (bytes that are not UTF-8)."""

    path: object
    scheme: str
    name: object
    header: object
    state: object
    successor_ref: object
    encoding_repaired: bool = False

    @property
    def number(self):
        return self.name.number

    @property
    def key(self):
        return (self.name.number, self.name.version, self.name.revision or 0)


@dataclass(frozen=True)
class Snapshot:
    """Every decision (sorted by number, version, revision, path), the
    same decisions grouped by number, in that order, and the `.md` files
    left out because their real path escapes the folder (a junction or
    symlink)."""

    decisions: tuple
    by_number: dict
    excluded: tuple = ()


def derive_state(header):
    """The state a valid header's status cells name, or None outside the
    closed set."""
    cells = (header.status_create, header.status_update, header.status_change)
    state = _CLOSED_SET.get(cells)
    if state is None and header.is_migrated:
        state = _MIGRATED_CLOSED_SET.get(cells)
    return state


def _successor_ref(header, state):
    if state != SUPERSEDED:
        return None
    return ascii_digits_int(header.superseded_by_file)


def _has_conflict_markers(lines):
    # "=======" alone is also a Markdown setext underline, so only the
    # opener or closer marks a conflict.
    return any(line.startswith(_CONFLICT_MARKERS) for line in lines)


def _error(code, path, related=(), detail=None):
    return {
        "code": code,
        "file": str(path),
        "related_files": sorted(str(item) for item in related),
        "detail": detail,
        "hint": HINTS[code],
    }


def _read_decisions(scan, config, errors):
    for directory in scan.unreadable:
        errors.append(_error(FailureCodes.SCAN_INCOMPLETE, directory))
    decisions = []
    for path in scan.markdown:
        found = parse_any_filename(path.name, config)
        if found is None:
            continue
        scheme, parsed = found
        try:
            lines, encoding_repaired = read_header_lines_with_report(path)
        except OSError as error:
            errors.append(_error(FailureCodes.SCAN_INCOMPLETE, path, detail=str(error)))
            continue
        if _has_conflict_markers(lines):
            errors.append(_error(FailureCodes.MERGE_CONFLICT_MARKERS, path))
            state, header = None, None
        else:
            header = parse_header(lines, config)
            state = None
            if not header.is_valid:
                if has_header_shape(lines):
                    errors.append(_error(FailureCodes.INVALID_HEADER, path, detail=describe_header_error(header)))
                else:
                    errors.append(_error(FailureCodes.NO_HEADER, path))
            else:
                state = derive_state(header)
                if state is None:
                    errors.append(_error(FailureCodes.INVALID_STATUS_COMBINATION, path))
        decisions.append(
            Decision(path, scheme, parsed, header, state, _successor_ref(header, state), encoding_repaired)
        )
    decisions.sort(key=lambda d: (*d.key, str(d.path)))
    return decisions


def _check_numbering(decisions, errors):
    by_key = {}
    for decision in decisions:
        by_key.setdefault(decision.key, []).append(decision)
    for group in by_key.values():
        if len(group) > 1:
            paths = sorted(str(d.path) for d in group)
            errors.append(_error(FailureCodes.DUPLICATE_NUMBER, paths[0], paths[1:]))


def _live_blocker(decision, family):
    """The member locking `decision`, per family.locking_member, over
    the family members whose state is known."""
    members = [(d.name, d.header, d.path) for d in family if d.state is not None]
    blocker = locking_member(decision.name, members)
    return None if blocker is None else blocker[2]


def _check_family(family, errors):
    for state, duplicate_code, not_live_code in (
        (PROPOSED, FailureCodes.PENDING_DUPLICATE, FailureCodes.PENDING_NOT_LIVE),
        (SUPERSEDED, FailureCodes.SUPERSEDED_DUPLICATE, FailureCodes.SUPERSEDED_NOT_LIVE),
    ):
        members = [d for d in family if d.state == state]
        if len(members) > 1:
            paths = sorted(str(d.path) for d in members)
            errors.append(_error(duplicate_code, paths[0], paths[1:]))
        for member in members:
            blocker = _live_blocker(member, family)
            if blocker is not None:
                errors.append(_error(not_live_code, member.path, [blocker]))
    rejected_successors = [d.path for d in family if d.state == REJECTED and is_successor(d.name)]
    if rejected_successors:
        for member in family:
            if member.state is not None and member.state != REJECTED:
                errors.append(_error(FailureCodes.REJECTED_SUCCESSOR_FAMILY_NOT_FINAL, member.path, rejected_successors))


def _check_supersede(decisions, by_number, errors):
    live_successors = {}
    for decision in decisions:
        if decision.state is not None and decision.state != REJECTED and is_successor(decision.name):
            live_successors.setdefault(decision.name.superseded_from, []).append(decision)

    for decision in decisions:
        if decision.state != SUPERSEDED:
            continue
        ref = decision.successor_ref
        named = [
            d
            for d in live_successors.get(decision.number, ())
            if ref is not None and d.number == ref
        ]
        if not named:
            related = [d.path for d in by_number.get(ref, ())] if ref is not None else []
            errors.append(_error(FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR, decision.path, related))

    for predecessor, successors in live_successors.items():
        if len(successors) > 1:
            paths = sorted(str(d.path) for d in successors)
            errors.append(_error(FailureCodes.MULTIPLE_LIVE_SUCCESSORS, paths[0], paths[1:]))
        for successor in successors:
            pointing = [
                d
                for d in by_number.get(predecessor, ())
                if d.state == SUPERSEDED and d.successor_ref == successor.number
            ]
            if not pointing:
                related = [d.path for d in by_number.get(predecessor, ())]
                errors.append(_error(FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR, successor.path, related))


def check_repository(folder, config, scan=None):
    """(Snapshot, errors) for the decisions under `folder`, read with
    `config`. `errors` is sorted by file, then code; empty when every
    invariant holds. A missing folder is an empty, consistent repository.
    `scan`: the folder's scan_tree when the caller already walked it
    (nothing is walked twice)."""
    errors = []
    if not folder.is_dir():
        scan = None
    elif scan is None:
        scan = scan_tree(folder)
    decisions = _read_decisions(scan, config, errors) if scan is not None else []
    by_number = {}
    for decision in decisions:
        by_number.setdefault(decision.number, []).append(decision)
    by_number = {number: tuple(family) for number, family in by_number.items()}

    _check_numbering(decisions, errors)
    for family in by_number.values():
        _check_family(family, errors)
    _check_supersede(decisions, by_number, errors)

    errors.sort(key=lambda error: (error["file"], error["code"]))
    return Snapshot(tuple(decisions), by_number, scan.excluded if scan is not None else ()), errors


def validate_repository(folder, config, scan=None, tolerate=()):
    """The Snapshot of a consistent repository; raises
    repository-inconsistent, with every broken invariant in
    data.errors ({code, file, related_files, detail, hint}), otherwise.
    `scan` as in check_repository. Errors whose code is in `tolerate` do
    not count (config tolerates no-header: a repository not yet migrated
    has it by definition, and config sets migrate's migrationpattern)."""
    snapshot, errors = check_repository(folder, config, scan)
    errors = [error for error in errors if error["code"] not in tolerate]
    if errors:
        raise CommandError(
            FailureCodes.REPOSITORY_INCONSISTENT,
            f"The decisions folder breaks {len(errors)} consistency rule(s); nothing was changed. "
            "Each entry in data.errors names the file, the rule and a repair hint.",
            data={"errors": errors},
        )
    return snapshot
