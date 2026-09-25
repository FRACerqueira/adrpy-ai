"""The repository model and its validator.

One scan of the decisions folder (core/fs.scan_tree) gives a `Decision`
for every file with an ADR name -- a `.md` whose name matches neither
naming scheme is not a decision and is ignored. The phase rule
(decision_names) narrows that for a legacy-scheme name: once any file
has a valid header migrate did not write (migrate no longer runs), one
without a header is not a decision either (before that it is a
no-header one, until migrate). Each decision's `state`
is derived once, from a closed set of status combinations (the ones the
tool itself writes, plus the migrated shapes). `check_repository`
returns the snapshot with every broken invariant it finds;
`validate_repository` raises repository-inconsistent when there is any.

The invariants, one error code each (HINTS has a repair hint per code;
successor-without-predecessor and superseded-not-live get theirs built
per error, with the literal header rows to write):

- header: merge-conflict markers in the 12 header lines are reported
  first, and alone (a supersede link to or from such a file is not also
  reported broken while the conflict exists); then no-header (nothing like this tool's header) or
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
from adrpy.core.fs import is_zero_bytes, scan_tree
from adrpy.core.family import is_successor, locking_member
from adrpy.core.header import (
    describe_header_error,
    has_header_shape,
    parse_header,
    read_header_lines_with_report,
    status_row,
)
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
        "The header holds git merge-conflict markers (a line starting '<<<<<<< ' or '>>>>>>> '). Resolve the conflict "
        "by hand, keeping one version of each of the 12 header lines, then run adrpy check again."
    ),
    FailureCodes.NO_HEADER: (
        "The file has an ADR name but no header. If it is empty (detail says 0-byte file), it was left by an "
        "interrupted create: remove it. If it is a decision written before adopting the tool and "
        "no decision was created with the tool yet, run adrpy migrate (it runs only once, before any "
        "new; set migrationpattern with adrpy config first: migrate always needs one). If it is not a "
        "decision (a note whose name the pattern happens to match), move it out of the decisions folder "
        "first: migrate would make it one. Otherwise migrate refuses: give it a header by hand (copy one from a decision the tool "
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
        "any successor that supersedes it -- and set the renamed file's header Version/Revision cells to "
        "match its new name."
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
        "the live member (only an Accepted one can carry it: its Changed cell must be Accepted), or set the "
        "newer member's Changed cell to Rejected."
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
    same decisions grouped by number, in that order, the `.md` files
    left out because their real path escapes the folder (a junction or
    symlink), and the legacy-scheme names the phase rule leaves out
    (`unheadered_legacy`, see decision_names)."""

    decisions: tuple
    by_number: dict
    excluded: tuple = ()
    unheadered_legacy: tuple = ()


@dataclass(frozen=True)
class DecisionName:
    """One file of a scan whose name is a decision's: its scheme and
    ParsedFileName, and its header lines as read (`lines`,
    `encoding_repaired`), or the OSError the read raised (`read_error`)."""

    path: object
    scheme: str
    parsed: object
    lines: object = None
    encoding_repaired: bool = False
    read_error: object = None


def _is_unheadered(lines, config):
    """No header at all: nothing parses, and nothing has this tool's
    header shape or merge-conflict markers (a 0-byte file included) --
    the no-header case of _read_decisions."""
    return (
        not _has_conflict_markers(lines)
        and not parse_header(lines, config).is_valid
        and not has_header_shape(lines)
    )


def decision_names(scan, config):
    """(names, unheadered_legacy) for the `.md` files of `scan`: every
    DecisionName, and the paths the phase rule leaves out. The rule: once
    any file whose name is a decision's (either scheme) has a valid header
    migrate did not write -- created by the tool or AdrPlus, or copied by
    hand, the point after which migrate no longer runs
    (already-tool-created-adrs-exist) -- a legacy-scheme name (recognized
    only through migrationpattern) with no header at all is not a
    decision; before that, it is one (no-header, until migrate: migrated
    headers alone keep it so, and a partial migrate's leftovers block the
    lifecycle commands until migrate finishes them). A header-shaped
    file that does not parse, a merge conflict or an unreadable file never
    adopts the repository and is never left out. The one reading of "is
    this a decision" for every consumer; migrate's own discovery alone
    still reads names (parse_any_filename), to migrate what is left out."""
    names = []
    adopted = False
    for path in scan.markdown:
        found = parse_any_filename(path.name, config)
        if found is None:
            continue
        scheme, parsed = found
        try:
            lines, encoding_repaired = read_header_lines_with_report(path)
        except OSError as error:
            names.append(DecisionName(path, scheme, parsed, read_error=error))
            continue
        names.append(DecisionName(path, scheme, parsed, lines, encoding_repaired))
        if not adopted and not _has_conflict_markers(lines):
            header = parse_header(lines, config)
            adopted = header.is_valid and not header.is_migrated
    if not adopted:
        return names, []
    unheadered = [
        name.path
        for name in names
        if name.scheme == "legacy" and name.read_error is None and _is_unheadered(name.lines, config)
    ]
    left_out = set(unheadered)
    return [name for name in names if name.path not in left_out], unheadered


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


def _status_cells(header):
    """The three status cells as read, for invalid-status-combination."""
    created, changed, superseded = (
        status or "blank" for status in (header.status_create, header.status_update, header.status_change)
    )
    return f"Created: {created}; Changed: {changed}; Superseded: {superseded}."


def _error(code, path, related=(), detail=None, hint=None):
    return {
        "code": code,
        "file": str(path),
        "related_files": sorted(str(item) for item in related),
        "detail": detail,
        "hint": hint or HINTS[code],
    }


def _replace_row(path, label, row):
    return f"in {path}, replace the row starting '|{label}|' with: {row}"


def _numbered(options):
    return "; ".join(f"{index}) {option}" for index, option in enumerate(options, 1))


def _can_carry_superseded(decision):
    # Only an Accepted decision (or a migrated placeholder) is ever marked
    # Superseded.
    return decision is not None and decision.state in (ACCEPTED, PLACEHOLDER)


def _successor_without_predecessor_hint(config, successor, family):
    """The repairs of a successor nothing points back at, most preferred
    first, each with the literal row to write."""
    number = f"{successor.number:0{config.lenseq}d}"
    predecessor = f"{successor.name.superseded_from:0{config.lenseq}d}"
    known = [d for d in family if d.state is not None and d.state != REJECTED]
    live = max(known, key=lambda d: d.key) if known else None
    options = []
    if _can_carry_superseded(live):
        row = status_row(
            config, config.headertitlestatussuperseded, "Superseded", successor.header.date_create, suffix=f" : {number}"
        )
        options.append(f"finish the supersede: {_replace_row(live.path, config.headertitlestatussuperseded, row)}")
    rejected = status_row(config, config.headertitlestatuschanged, "Rejected", None)
    options.append(f"drop this successor: {_replace_row(successor.path, config.headertitlestatuschanged, rejected)}")
    options.append("remove it if it was just created from the template")
    sep = config.separator * 2
    return (
        f"A successor that is not Rejected has no member of family {predecessor} whose Superseded cell points back "
        "at it, usually a supersede (or a reject) that stopped halfway. By hand (commands refuse this repository), "
        f"in order of preference: {_numbered(options)}. Do not rename it: the {sep}{predecessor} suffix is what "
        f"links it to {predecessor}."
    )


def _superseded_not_live_hint(config, decision, blocker):
    """The repairs of a Superseded cell on a member that is not the live
    one, most preferred first, each with the literal row(s) to write."""
    label = config.headertitlestatussuperseded
    options = []
    if _can_carry_superseded(blocker):
        moved = status_row(
            config, label, "Superseded", decision.header.date_change, suffix=f" : {decision.header.superseded_by_file}"
        )
        options.append(
            f"move the Superseded cell to the live member: {_replace_row(blocker.path, label, moved)}, "
            f"and {_replace_row(decision.path, label, status_row(config, label, None, None))}"
        )
    rejected = status_row(config, config.headertitlestatuschanged, "Rejected", None)
    options.append(f"drop the newer member: {_replace_row(blocker.path, config.headertitlestatuschanged, rejected)}")
    return (
        "A Superseded decision is not the live member of its family: a newer member that is not Rejected "
        f"(related_files) locks it. By hand (commands refuse this repository), in order of preference: "
        f"{_numbered(options)}."
        + (
            ""
            if _can_carry_superseded(blocker)
            else " Only an Accepted member can carry the Superseded cell, so it cannot move to the newer one."
        )
    )


def _read_decisions(names, config, errors):
    decisions = []
    for name in names:
        path, scheme, parsed = name.path, name.scheme, name.parsed
        if name.read_error is not None:
            errors.append(_error(FailureCodes.SCAN_INCOMPLETE, path, detail=str(name.read_error)))
            continue
        lines, encoding_repaired = name.lines, name.encoding_repaired
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
                    detail = "0-byte file (most likely left by an interrupted create)." if not lines and is_zero_bytes(path) else None
                    errors.append(_error(FailureCodes.NO_HEADER, path, detail=detail))
            else:
                state = derive_state(header)
                if state is None:
                    errors.append(
                        _error(FailureCodes.INVALID_STATUS_COMBINATION, path, detail=_status_cells(header))
                    )
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


def _check_family(family, config, errors):
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
                hint = None
                if state == SUPERSEDED:
                    blocking = next(d for d in family if d.path == blocker)
                    hint = _superseded_not_live_hint(config, member, blocking)
                errors.append(_error(not_live_code, member.path, [blocker], hint=hint))
    rejected_successors = [d.path for d in family if d.state == REJECTED and is_successor(d.name)]
    if rejected_successors:
        for member in family:
            if member.state is not None and member.state != REJECTED:
                errors.append(_error(FailureCodes.REJECTED_SUCCESSOR_FAMILY_NOT_FINAL, member.path, rejected_successors))


def _check_supersede(decisions, by_number, config, errors):
    # A file with merge-conflict markers keeps its name (and number) but
    # has no known state; the supersede links it may complete are not
    # reported as broken while the conflict exists (the conflict is).
    conflicted = [d for d in decisions if d.header is None]
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
        if not named and any(d.number == ref and d.name.superseded_from == decision.number for d in conflicted):
            continue
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
            if not pointing and any(d.number == predecessor for d in conflicted):
                continue
            if not pointing:
                family = by_number.get(predecessor, ())
                errors.append(
                    _error(
                        FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR,
                        successor.path,
                        [d.path for d in family],
                        hint=_successor_without_predecessor_hint(config, successor, family),
                    )
                )


def unrecognized_decision_like_warning(scan, config):
    """The warning for `.md` files of `scan` that have no ADR name but
    look like decisions (the name starts with a digit, as in
    `0001-use-x.md`) -- written before adrpy, and invisible to every rule
    until migrationpattern names them. None when there are none (a
    README.md or INDEX.md never counts)."""
    if scan is None:
        return None
    names = sorted(
        path.name
        for path in scan.markdown
        if path.name[:1].isascii() and path.name[:1].isdigit() and parse_any_filename(path.name, config) is None
    )
    if not names:
        return None
    found = f"{len(names)} .md file(s) in {config.folderadr} are not recognized: {', '.join(names)}."
    if config.migrationpattern:
        found += f" migrationpattern ('{config.migrationpattern}') does not match them."
    preview = "preview a pattern with `adrpy explore --path . --migrationpattern <pattern>` (it writes nothing)"
    if _has_tool_created_decision(scan, config):
        # migrate refuses here (already-tool-created-adrs-exist), and a
        # name migrationpattern matches without a header is not a
        # decision here (decision_names).
        return (
            f"{found} If they are decisions written before adrpy: migrate does not run in a repository that "
            f"already has decisions the tool created, so {preview}, set migrationpattern with `adrpy config "
            "--migrationpattern` (it writes the config) and give each one a header by hand (copy one from a "
            "decision the tool created) -- without one, a name migrationpattern matches is still not a decision."
        )
    return (
        f"{found} If they are decisions written before adrpy, {preview}, then set migrationpattern with "
        "`adrpy config --migrationpattern` (it writes the config) and run `adrpy migrate`."
    )


def unheadered_legacy_warning(snapshot):
    """The warning for the legacy-scheme names the phase rule left out of
    `snapshot` (decision_names): not decisions, and invisible to every
    rule. None when there are none."""
    if not snapshot.unheadered_legacy:
        return None
    names = sorted(path.name for path in snapshot.unheadered_legacy)
    found = (
        f"{len(names)} file(s) match migrationpattern but have no header, so they are not decisions: "
        f"{', '.join(names)}."
    )
    # Left out only once a decision migrate did not write exists, so
    # migrate no longer runs here.
    return (
        f"{found} If they are decisions written before adrpy: migrate does not run in a repository that "
        "already has decisions the tool created, so give each one a header by hand (copy one from a "
        "decision the tool created) -- its number, read from the name, may already be a decision's: "
        "rename it to a free number first; otherwise move them out of the decisions folder."
    )


def _has_tool_created_decision(scan, config):
    """Whether a file of `scan` with an ADR name has a valid header migrate
    did not write (AdrPlus or adrpy)."""
    for path in scan.markdown:
        if parse_any_filename(path.name, config) is None:
            continue
        try:
            lines, _encoding_repaired = read_header_lines_with_report(path)
        except OSError:
            continue
        header = parse_header(lines, config)
        if header.is_valid and not header.is_migrated:
            return True
    return False


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
    decisions, unheadered = [], []
    if scan is not None:
        for directory in scan.unreadable:
            errors.append(_error(FailureCodes.SCAN_INCOMPLETE, directory))
        names, unheadered = decision_names(scan, config)
        decisions = _read_decisions(names, config, errors)
    by_number = {}
    for decision in decisions:
        by_number.setdefault(decision.number, []).append(decision)
    by_number = {number: tuple(family) for number, family in by_number.items()}

    _check_numbering(decisions, errors)
    for family in by_number.values():
        _check_family(family, config, errors)
    _check_supersede(decisions, by_number, config, errors)

    errors.sort(key=lambda error: (error["file"], error["code"]))
    excluded = scan.excluded if scan is not None else ()
    return Snapshot(tuple(decisions), by_number, excluded, tuple(unheadered)), errors


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
        raise inconsistent_repository(errors)
    return snapshot


def inconsistent_repository(errors):
    """The repository-inconsistent CommandError for check_repository's
    `errors` (validate_repository's, and `check`'s own)."""
    return CommandError(
        FailureCodes.REPOSITORY_INCONSISTENT,
        f"The decisions folder breaks {len(errors)} consistency rule(s); nothing was changed. "
        "Each entry in data.errors names the file, the rule and a repair hint.",
        data={"errors": errors},
    )
