"""`undo` command: reverts a decision's update status back to blank
(harness Fase 7, item 4). Ported from UndoStatusCommandHandler.cs. No
--refdate -- the original clears the "Changed" row entirely rather than
recording a new transition.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    family_members,
    has_pending_sibling,
    has_superseded_sibling,
    ineligibility_reason_for_undo,
    load_target,
    rewrite_status_field,
)
from adrpy.core.security import resolve_within
from adrpy.core.warnings import encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "still-proposed": "This decision has never been approved or rejected; there is nothing to undo.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
}


def describe():
    return {
        "name": "undo",
        "description": "Reverts a decision's Accepted/Rejected status back to Proposed.",
        "arguments": [
            {"name": "file", "type": "string", "required": True, "description": "Path to the decision file."},
        ],
    }


def run(args):
    flags = parse_flags(args, required=("file",), aliases={"f": "file"})
    config, root, path, filename_info, header, lines, encoding_repaired = load_target(flags["file"])
    warnings = []
    if encoding_repaired:
        warnings.append(encoding_repaired_warning(path))

    # Usability audit: a specific reason code instead of one collapsed
    # not-eligible-for-undo.
    reason = ineligibility_reason_for_undo(header)
    if reason is not None:
        raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

    folder = resolve_within(root, config.folderadr)
    if folder.is_dir():
        warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder))
        if warning:
            warnings.append(warning)
    # Performance backlog item: one scan, shared by both checks below --
    # each used to call family_members (and so scan_decisions) on its own.
    members = family_members(folder, config, filename_info.number)
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

    _record, _content, attempts = rewrite_status_field(
        path, config, lines, header, filename_info, field="update", status=None, refdate=None
    )
    warning = retry_warning(attempts)
    if warning:
        warnings.append(warning)

    # Usability audit M4: canonical keyword, not the repo's configured label.
    return {"file": str(path), "status": "Proposed", "warnings": warnings}
