"""`undo` command: reverts a decision's update status back to blank. No
--refdate -- clears the "Changed" row entirely rather than recording a
new transition.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import SHARED_FAILURE_CODES as HEADER_FAILURE_CODES
from adrpy.core.lifecycle import (
    raise_if_superseded_sibling,
    raise_if_pending_sibling,
    raise_if_not_latest,
    raise_if_rejected_successor,
    SHARED_FAILURE_CODES as LIFECYCLE_FAILURE_CODES,
    family_members,
    ineligibility_reason_for_undo,
    load_target,
    rewrite_status_field,
)
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    FailureCodes.STILL_PROPOSED: "This decision has never been approved or rejected; there is nothing to undo.",
    FailureCodes.ALREADY_SUPERSEDED: "This decision has already been superseded.",
    FailureCodes.NOT_PROPOSED: "This decision's own Created status is not Proposed -- no command writes that; repair its Created cell by hand.",
}


def describe():
    return {
        "name": "undo",
        "summary": "Reverts a decision's Accepted/Rejected status back to Proposed.",
        "description": (
            "Reverts a decision's Accepted/Rejected status back to Proposed. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "May also fail with family-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "can't be trusted from an incomplete scan; no write was made. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). "
            "The target's own title/"
            "scope/domain (re-read from its header cells, not flags) are re-validated before use -- may fail "
            "with field-contains-forbidden-character if a hand-edited or migrated source file's title "
            "carries '|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a "
            "control character), or consists entirely of whitespace/'_'/'-'. Fails with one of "
            "still-proposed, already-superseded, or not-proposed if the target isn't eligible, or "
            "family-member-superseded/family-member-pending if another member of the same family has "
            "already been superseded or is still unresolved (Proposed). Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Fails with "
            "rejected-successor-is-final if the target belongs to the family of a successor that was "
            "rejected -- the end of its line. No write is made in any of "
            "these cases."
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
        "failure_codes": build_failure_codes(
            _INELIGIBILITY_DETAILS,
            {
                FailureCodes.NOT_LATEST_VERSION: "A newer member of this family locks this one -- only the latest member can change, unless every newer one is Rejected (data.latest_file names the newer file).",
                FailureCodes.REJECTED_SUCCESSOR_IS_FINAL: "This decision belongs to the family of a successor that was rejected -- the end of its line; supersede its predecessor again instead (data.successor_file, data.predecessor_number).",
                FailureCodes.FAMILY_MEMBER_PENDING: "Another member of the same family is still unresolved (Proposed) -- undo would leave two.",
            },
            LIFECYCLE_FAILURE_CODES,
            HEADER_FAILURE_CODES,
            CONFIG_FAILURE_CODES,
        ),
    }


def run(args):
    flags = parse_flags(args, required=("file",), aliases={"f": "file"})
    warnings = []
    config, root, path, filename_info, header, encoding_repaired = load_target(flags["file"], warnings=warnings)
    folder = resolve_within(root, config.folderadr)
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # A specific reason code, not one collapsed not-eligible-for-undo,
        # so the caller knows which recovery action applies.
        reason = ineligibility_reason_for_undo(header)
        if reason is not None:
            raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

        # One scan shared by both checks below, avoiding a duplicate
        # scan_decisions call each.
        members = family_members(
            folder, config, filename_info.number, warnings=warnings
        )
        raise_if_superseded_sibling(members, warnings)
        raise_if_pending_sibling(members, warnings, " -- undo would leave two")
        raise_if_not_latest(filename_info, members, warnings)
        raise_if_rejected_successor(members, warnings)

        # title/scope/domain are re-read from the SOURCE
        # file's own header cells, not flags -- a hand-edited or
        # migrated file could carry a filesystem-unsafe character
        # (e.g. ':', an NTFS Alternate-Data-Stream separator) never
        # validated until this rewrite. Same defensive re-validation
        # version/revise/supersede/migrate already apply.
        reject_embedded_delimiter(header.title, "title")
        reject_filesystem_unsafe_title(header.title, "title")
        reject_title_with_no_case_transform_content(header.title, "title")
        reject_embedded_delimiter(header.scope, "scope")
        reject_embedded_delimiter(header.domain, "domain")

        _record, body_encoding_repaired, attempts = rewrite_status_field(
            path, config, header, filename_info, field="update", status=None, refdate=None
        )
        # Accurate only because the write above already succeeded --
        # the warning claims the file was rewritten. ADR006V01:
        # combines the header's own flag (known since load_target)
        # with the body's own (only known now, from the streamed
        # write).
        if encoding_repaired or body_encoding_repaired:
            warnings.append(encoding_repaired_warning(path))
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"file": str(path), "status": "Proposed", "warnings": warnings}
