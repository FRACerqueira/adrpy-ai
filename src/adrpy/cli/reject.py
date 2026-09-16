"""`reject` command: marks a Proposed decision as Rejected (harness Fase 7,
item 4). Ported from RejectCommandHandler.cs. When the rejected decision
was itself a successor (its filename carries a supersede suffix), the
predecessor's Superseded status is undone too -- the attempted supersession
failed along with the successor.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    family_members,
    has_superseded_sibling,
    ineligibility_reason_for_approve_or_reject,
    latest_in_family,
    parse_refdate,
    read_lines_with_report,
    read_target,
    resolve_repo_and_target,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import LockLostError, acquire_repo_lock
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "already-accepted": "This decision is already Accepted; run undo first to reconsider it.",
    "already-rejected": "This decision is already Rejected.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
    "unexpected-status": "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "reject",
        "description": (
            "Marks a Proposed decision as Rejected. If this decision is itself a successor "
            "(created by `supersede`), also reverts the predecessor's Superseded status -- the "
            "result's `undone_predecessor` names that file when this happens, or is null otherwise. "
            "This is two writes in sequence, not one: a failure reverting the predecessor "
            "(superseded-predecessor-not-found, reject-predecessor-write-failed) means success=false "
            "even though this decision's OWN status was already committed to Rejected -- that code's "
            "own `data.file`/`data.status` names the file already mutated despite the overall failure "
            "(a lock lost before this SECOND write also surfaces reject-predecessor-write-failed, not "
            "lock-lost). May instead fail with repository-locked (lock never acquired) or lock-lost (lost "
            "before the FIRST write) -- in both of those cases no write was made at all."
        ),
        "arguments": [
            {
                "name": "file",
                "type": "string",
                "required": True,
                "description": "Path to the decision file. A bare name with no extension gets '.md' appended.",
            },
            {
                "name": "refdate",
                "type": "string",
                "required": False,
                "description": "Reference date (YYYY-MM-DD); defaults to today.",
            },
        ],
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("refdate",), aliases={"f": "file", "r": "refdate"})
    config, root, path = resolve_repo_and_target(flags["file"])
    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder))
            if warning:
                warnings.append(warning)

        # Round 4 ADR001 (doc/adr/ADR001V01-...): reject held no lock at
        # all (stability audit Finding 1, reproduced -- see approve.py's
        # own comment). The read below now happens fresh, inside the lock.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Round 6 stability re-run, root cause shared by 8 call
            # sites -- see approve.py's own comment.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, lines, encoding_repaired = read_target(path, config)

            # Usability audit: a specific reason code instead of one collapsed
            # not-eligible-for-rejection.
            reason = ineligibility_reason_for_approve_or_reject(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

            # Performance backlog item's own pattern applied here too:
            # pre-fetching members is also how the scan's own warnings=
            # (round 4 observability audit, Finding 3) reach this command.
            members = family_members(folder, config, filename_info.number, warnings=warnings)
            if has_superseded_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    "family-member-superseded",
                    "A sibling decision in this family has already been superseded.",
                    warnings=warnings,
                )

            refdate = parse_refdate(flags.get("refdate"))
            validate_refdate_not_in_future(refdate)
            if header.date_create is not None:
                validate_refdate_not_before(refdate, header.date_create)

            # ADR001, part 3: guarantees this write (and the predecessor's,
            # below) never commit blindly if the lease was reclaimed.
            lock.verify_still_held()
            _record, _content, attempts = rewrite_status_field(
                path, config, lines, header, filename_info, field="update", status="Rejected", refdate=refdate
            )
            # Round 4 resilience audit, Finding 1: only true once the write
            # above has actually happened -- see approve.py's own comment.
            if encoding_repaired:
                warnings.append(encoding_repaired_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

            undone_predecessor = None
            if filename_info.superseded_from is not None:
                pred_members = family_members(folder, config, filename_info.superseded_from, warnings=warnings)
                predecessor = latest_in_family(folder, config, filename_info.superseded_from, members=pred_members)
                if predecessor is None:
                    # Mechanism-correctness audit round 2 (findings #3/#4): by this
                    # point the primary write above has already succeeded for
                    # real -- `path` genuinely is Rejected on disk. `data` names
                    # that partial success explicitly, so a caller doesn't have to
                    # infer it from `warnings` alone (there may be none) or
                    # discover it only by re-reading the file itself.
                    raise CommandError(
                        "superseded-predecessor-not-found",
                        f"Could not find the decision this one superseded (sequence {filename_info.superseded_from}).",
                        data={"file": str(path), "status": "Rejected"},
                        warnings=warnings,
                    )
                pred_parsed, pred_header, pred_path = predecessor
                pred_lines, pred_encoding_repaired = read_lines_with_report(pred_path)
                try:
                    # ADR001, part 3: this is this command's SECOND write --
                    # guarantees it never commits blindly either, on its own,
                    # even though the first write above already succeeded.
                    lock.verify_still_held()
                    _record, _content, attempts = rewrite_status_field(
                        pred_path,
                        config,
                        pred_lines,
                        pred_header,
                        pred_parsed,
                        field="change",
                        status=None,
                        refdate=None,
                    )
                    # Round 4 resilience audit, Finding 1: only true once
                    # this second write has actually happened -- see
                    # approve.py's own comment.
                    if pred_encoding_repaired:
                        warnings.append(encoding_repaired_warning(pred_path))
                except (OSError, LockLostError) as error:
                    # Mechanism-correctness audit round 3 (resilience finding
                    # #1): by this point the primary write above has already
                    # succeeded for real -- `path` genuinely is Rejected on
                    # disk. Same partial-success shape as this command's own
                    # superseded-predecessor-not-found case, just for a real
                    # OSError instead of a missing predecessor.
                    #
                    # Round 5 stability re-run, Finding 3: LockLostError
                    # used to bypass this handler entirely (only OSError
                    # was caught), reporting a generic, dataless lock-lost
                    # even though the primary write above already
                    # committed for real. Reuses this command's own
                    # existing code/data shape rather than inventing a
                    # parallel one.
                    raise CommandError(
                        "reject-predecessor-write-failed",
                        f"{pred_path}: {error}",
                        data={"file": str(path), "status": "Rejected", "predecessor_file": str(pred_path)},
                        warnings=warnings,
                    ) from error
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(warning)
                undone_predecessor = str(pred_path)

    # Usability audit M4: canonical keyword, not the repo's configured label.
    return {"file": str(path), "status": "Rejected", "undone_predecessor": undone_predecessor, "warnings": warnings}
