"""`approve` command: marks a Proposed decision as Accepted (harness Fase 7,
item 4). Ported from ApproveCommandHandler.cs.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    family_members,
    has_superseded_sibling,
    ineligibility_reason_for_approve_or_reject,
    parse_refdate,
    read_target,
    resolve_repo_and_target,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "already-accepted": "This decision is already Accepted.",
    "already-rejected": "This decision is already Rejected; run undo first to reconsider it.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
    "unexpected-status": "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "approve",
        "description": (
            "Marks a Proposed decision as Accepted. "
            "May fail with repository-locked if the repository lock could not be acquired in time, or "
            "lock-lost if it was acquired but reclaimed by another process before the write could commit -- "
            "in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write was "
            "made either way; retry."
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
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # Round 4 ADR001 (doc/adr/ADR001V01-...): approve held no lock at
        # all -- two concurrent approve/reject calls on the same file both
        # read-decided-wrote independently and both reported success with
        # mutually exclusive final statuses (stability audit Finding 1,
        # reproduced). The read below now happens fresh, inside the lock,
        # instead of before it.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Round 6 stability re-run, root cause shared by 8 call
            # sites: `folder` above was resolved from a config read
            # BEFORE this lock -- a concurrent config change could have
            # moved folderadr in the window before the lock was
            # actually acquired, in which case this lock no longer
            # names the repository's real decisions folder. Re-reads
            # fresh and aborts rather than operating against a
            # directory nobody uses anymore.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, lines, encoding_repaired = read_target(path, config)

            # Usability audit: a specific reason code instead of one collapsed
            # not-eligible-for-approval -- already-accepted/already-rejected/
            # already-superseded each call for a different recovery action.
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

            # ADR001, part 3: the lease can still be reclaimed out from
            # under a legitimately slow holder -- this can't prevent that,
            # but guarantees the write below never commits blindly if it
            # already happened.
            lock.verify_still_held()
            _record, _content, attempts = rewrite_status_field(
                path, config, lines, header, filename_info, field="update", status="Accepted", refdate=refdate
            )
            # Round 4 resilience audit, Finding 1: encoding_repaired_warning
            # claims "the file has been rewritten... bytes are now lost" --
            # only true once the write above has actually happened, not at
            # read time (an eligibility check could still have failed first).
            if encoding_repaired:
                warnings.append(encoding_repaired_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Usability audit M4: canonical keyword, matching explore's own
    # status_create/status_update -- not the repo's configured label.
    return {"file": str(path), "status": "Accepted", "warnings": warnings}
