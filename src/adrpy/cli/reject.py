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
    has_superseded_sibling,
    is_eligible_for_approve_or_reject,
    latest_in_family,
    load_target,
    parse_refdate,
    read_lines_with_report,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
)
from adrpy.core.security import resolve_within
from adrpy.core.warnings import encoding_repaired_warning, orphan_cleanup_warning, retry_warning


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
    flags = parse_flags(args, required=("file",), optional=("refdate",), aliases={"f": "file", "r": "refdate"})
    config, root, path, filename_info, header, lines, encoding_repaired = load_target(flags["file"])
    warnings = []
    if encoding_repaired:
        warnings.append(encoding_repaired_warning(path))

    if not is_eligible_for_approve_or_reject(header):
        raise CommandError(
            "not-eligible-for-rejection",
            "This decision cannot be rejected: it must be Proposed and not yet approved/rejected.",
        )

    folder = resolve_within(root, config.folderadr)
    if folder.is_dir():
        warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder))
        if warning:
            warnings.append(warning)
    if has_superseded_sibling(folder, config, filename_info.number):
        raise CommandError(
            "family-member-superseded", "A sibling decision in this family has already been superseded."
        )

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)
    if header.date_create is not None:
        validate_refdate_not_before(refdate, header.date_create)

    _record, _content, attempts = rewrite_status_field(
        path, config, lines, header, filename_info, field="update", status="Rejected", refdate=refdate
    )
    warning = retry_warning(attempts)
    if warning:
        warnings.append(warning)

    undone_predecessor = None
    if filename_info.superseded_from is not None:
        predecessor = latest_in_family(folder, config, filename_info.superseded_from)
        if predecessor is None:
            raise CommandError(
                "superseded-predecessor-not-found",
                f"Could not find the decision this one superseded (sequence {filename_info.superseded_from}).",
            )
        pred_parsed, pred_header, pred_path = predecessor
        pred_lines, pred_encoding_repaired = read_lines_with_report(pred_path)
        if pred_encoding_repaired:
            warnings.append(encoding_repaired_warning(pred_path))
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
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)
        undone_predecessor = str(pred_path)

    # Usability audit M4: canonical keyword, not the repo's configured label.
    return {"file": str(path), "status": "Rejected", "undone_predecessor": undone_predecessor, "warnings": warnings}
