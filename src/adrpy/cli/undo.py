"""`undo` command: reverts a decision's update status back to blank. No
--refdate -- clears the "Changed" row entirely rather than recording a
new transition.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    family_members,
    has_pending_sibling,
    has_superseded_sibling,
    ineligibility_reason_for_undo,
    read_target,
    resolve_repo_and_target,
    rewrite_status_field,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "still-proposed": "This decision has never been approved or rejected; there is nothing to undo.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
}


def describe():
    return {
        "name": "undo",
        "summary": "Reverts a decision's Accepted/Rejected status back to Proposed.",
        "description": (
            "Reverts a decision's Accepted/Rejected status back to Proposed. "
            "May fail with repository-locked if the repository lock could not be acquired in time, or "
            "lock-lost if it was acquired but reclaimed by another process before the write could commit -- "
            "in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write was "
            "made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "can't be trusted from an incomplete scan; no write was made."
        ),
        "arguments": [
            {
                "name": "file",
                "alias": "-f",
                "type": "string",
                "required": True,
                "description": "Path to the decision file. A bare name with no extension gets '.md' appended.",
            },
        ],
    }


def run(args):
    flags = parse_flags(args, required=("file",), aliases={"f": "file"})
    config, root, path = resolve_repo_and_target(flags["file"])
    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # ADR001's freshness principle (doc/adr/ADR001V01-...): the read
        # below happens fresh, inside the lock, never from a pre-lock read.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Re-reads fresh in case folderadr changed between the pre-lock
            # read and lock acquisition -- operating against a stale folder
            # would be silently wrong.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, lines, encoding_repaired = read_target(path, config)

            # A specific reason code, not one collapsed not-eligible-for-undo,
            # so the caller knows which recovery action applies.
            reason = ineligibility_reason_for_undo(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

            # One scan shared by both checks below, avoiding a duplicate
            # scan_decisions call each.
            members = family_members(folder, config, filename_info.number, warnings=warnings)
            if has_superseded_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    "family-member-superseded",
                    "A sibling decision in this family has already been superseded.",
                    warnings=warnings,
                )
            if has_pending_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    "family-member-pending",
                    "Another decision in this family is still unresolved (Proposed) -- undo would leave two.",
                    warnings=warnings,
                )

            lock.verify_still_held()
            _record, _content, attempts = rewrite_status_field(
                path, config, lines, header, filename_info, field="update", status=None, refdate=None
            )
            # Accurate only because the write above already succeeded --
            # the warning claims the file was rewritten.
            if encoding_repaired:
                warnings.append(encoding_repaired_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"file": str(path), "status": "Proposed", "warnings": warnings}
