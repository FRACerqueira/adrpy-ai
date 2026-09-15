"""`approve` command: marks a Proposed decision as Accepted (harness Fase 7,
item 4). Ported from ApproveCommandHandler.cs.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    has_superseded_sibling,
    ineligibility_reason_for_approve_or_reject,
    load_target,
    parse_refdate,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
)
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
        "description": "Marks a Proposed decision as Accepted.",
        "arguments": [
            {"name": "file", "type": "string", "required": True, "description": "Path to the decision file."},
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
    config, root, path, filename_info, header, lines, encoding_repaired = load_target(flags["file"])
    warnings = []
    with attach_warnings(warnings):
        if encoding_repaired:
            warnings.append(encoding_repaired_warning(path))

        # Usability audit: a specific reason code instead of one collapsed
        # not-eligible-for-approval -- already-accepted/already-rejected/
        # already-superseded each call for a different recovery action.
        reason = ineligibility_reason_for_approve_or_reject(header)
        if reason is not None:
            raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

        folder = resolve_within(root, config.folderadr)
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder))
            if warning:
                warnings.append(warning)
        if has_superseded_sibling(folder, config, filename_info.number):
            raise CommandError(
                "family-member-superseded",
                "A sibling decision in this family has already been superseded.",
                warnings=warnings,
            )

        refdate = parse_refdate(flags.get("refdate"))
        validate_refdate_not_in_future(refdate)
        if header.date_create is not None:
            validate_refdate_not_before(refdate, header.date_create)

        _record, _content, attempts = rewrite_status_field(
            path, config, lines, header, filename_info, field="update", status="Accepted", refdate=refdate
        )
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # Usability audit M4: canonical keyword, matching explore's own
    # status_create/status_update -- not the repo's configured label.
    return {"file": str(path), "status": "Accepted", "warnings": warnings}
