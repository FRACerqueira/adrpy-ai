"""`reject` command: marks a Proposed decision as Rejected (harness Fase 7,
item 4). Ported from RejectCommandHandler.cs. When the rejected decision
was itself a successor (its filename carries a supersede suffix), the
predecessor's Superseded status is undone too -- the attempted supersession
failed along with the successor.
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError
from adrpy.core.lifecycle import (
    has_superseded_sibling,
    is_eligible_for_approve_or_reject,
    latest_in_family,
    load_target,
    parse_refdate,
    read_lines,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
)
from adrpy.core.security import resolve_within


def describe():
    return {
        "name": "reject",
        "description": "Marks a Proposed decision as Rejected.",
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
            "not-eligible-for-rejection",
            "This decision cannot be rejected: it must be Proposed and not yet approved/rejected.",
        )

    folder = resolve_within(root, config.folderadr)
    if has_superseded_sibling(folder, config, filename_info.number):
        raise CommandError(
            "family-member-superseded", "A sibling decision in this family has already been superseded."
        )

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)
    if header.date_create is not None:
        validate_refdate_not_before(refdate, header.date_create)

    rewrite_status_field(
        path, config, lines, header, filename_info, field="update", status="Rejected", refdate=refdate
    )

    undone_predecessor = None
    if filename_info.superseded_from is not None:
        predecessor = latest_in_family(folder, config, filename_info.superseded_from)
        if predecessor is None:
            raise CommandError(
                "superseded-predecessor-not-found",
                f"Could not find the decision this one superseded (sequence {filename_info.superseded_from}).",
            )
        pred_parsed, pred_header, pred_path = predecessor
        rewrite_status_field(
            pred_path,
            config,
            read_lines(pred_path),
            pred_header,
            pred_parsed,
            field="change",
            status=None,
            refdate=None,
        )
        undone_predecessor = str(pred_path)

    return {"file": str(path), "status": config.statusrej, "undone_predecessor": undone_predecessor}
