"""`undo` command: reverts a decision's update status back to blank
(harness Fase 7, item 4). Ported from UndoStatusCommandHandler.cs. No
--refdate -- the original clears the "Changed" row entirely rather than
recording a new transition.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    has_pending_sibling,
    has_superseded_sibling,
    is_eligible_for_undo,
    load_target,
    rewrite_status_field,
)
from adrpy.core.security import resolve_within


def describe():
    return {
        "name": "undo",
        "description": "Reverts a decision's Accepted/Rejected status back to Proposed.",
        "arguments": [
            {"name": "file", "type": "string", "required": True, "description": "Path to the decision file."},
        ],
    }


def run(args):
    flags = parse_flags(args, required=("file",))
    config, root, path, filename_info, header, lines = load_target(flags["file"])

    if not is_eligible_for_undo(header):
        raise CommandError(
            "not-eligible-for-undo",
            "This decision cannot be undone: it must currently be Accepted or Rejected.",
        )

    folder = resolve_within(root, config.folderadr)
    if folder.is_dir():
        cleanup_orphaned_temp_files(folder)
    if has_superseded_sibling(folder, config, filename_info.number):
        raise CommandError(
            "family-member-superseded", "A sibling decision in this family has already been superseded."
        )
    if has_pending_sibling(folder, config, filename_info.number):
        raise CommandError(
            "family-member-pending",
            "Another decision in this family is still unresolved (Proposed) -- undo would leave two.",
        )

    rewrite_status_field(path, config, lines, header, filename_info, field="update", status=None, refdate=None)

    # Usability audit M4: canonical keyword, not the repo's configured label.
    return {"file": str(path), "status": "Proposed"}
