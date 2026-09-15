"""`approve` command: marks a Proposed decision as Accepted (harness Fase 7,
item 4). Ported from ApproveCommandHandler.cs.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    has_superseded_sibling,
    is_eligible_for_approve_or_reject,
    load_target,
    parse_refdate,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
)
from adrpy.core.security import resolve_within


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
    flags = parse_flags(args, required=("file",), optional=("refdate",))
    config, root, path, filename_info, header, lines = load_target(flags["file"])

    if not is_eligible_for_approve_or_reject(header):
        raise CommandError(
            "not-eligible-for-approval",
            "This decision cannot be approved: it must be Proposed and not yet approved/rejected.",
        )

    folder = resolve_within(root, config.folderadr)
    if folder.is_dir():
        cleanup_orphaned_temp_files(folder)
    if has_superseded_sibling(folder, config, filename_info.number):
        raise CommandError(
            "family-member-superseded", "A sibling decision in this family has already been superseded."
        )

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)
    if header.date_create is not None:
        validate_refdate_not_before(refdate, header.date_create)

    rewrite_status_field(
        path, config, lines, header, filename_info, field="update", status="Accepted", refdate=refdate
    )

    # Usability audit M4: canonical keyword, matching explore's own
    # status_create/status_update -- not the repo's configured label.
    return {"file": str(path), "status": "Accepted"}
