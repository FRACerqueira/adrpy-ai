"""`revise` command: creates a new revision (minor change) of an
Accepted/Rejected decision (harness Fase 7, item 6). Ported from
ReviseCommandHandler.cs. Unlike `version`, revise has no --scope/--domain
and no --empty -- it always carries the source's content forward, and its
scope/domain come from the TARGET file's own header (not the latest
member's), a genuine difference confirmed against the original. --open is
not implemented (see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.lifecycle import (
    has_pending_sibling,
    has_superseded_sibling,
    is_eligible_for_version_or_revise,
    latest_in_family,
    load_target,
    parse_refdate,
    read_body,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
)
from adrpy.core.naming import build_filename
from adrpy.core.security import resolve_within


def describe():
    return {
        "name": "revise",
        "description": "Creates a new revision (wording fix) of an Accepted/Rejected decision.",
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

    if config.lenrevision == 0:
        raise CommandError("revision-not-configured", "This repository's config has lenrevision == 0.")

    folder = resolve_within(root, config.folderadr)

    latest = latest_in_family(folder, config, filename_info.number)
    if latest is None:
        raise CommandError("family-not-found", "Could not resolve this decision's own family.")
    latest_parsed, latest_header, latest_path = latest

    if len(str((latest_parsed.revision or 0) + 1)) > config.lenrevision:
        raise CommandError(
            "lenrevision-too-small-for-new-revision",
            f"New revision {(latest_parsed.revision or 0) + 1} does not fit in lenrevision={config.lenrevision}.",
        )

    if latest_path.resolve() != path.resolve():
        # Same branch-off-a-rejected-latest exception as `version`, but
        # revision-only (revise never bumps the version number).
        allowed = latest_header.status_update == "Rejected" and (latest_parsed.revision or 0) > (
            filename_info.revision or 0
        )
        if not allowed:
            raise CommandError(
                "not-latest-version", "This decision is not the latest version/revision in its family."
            )

    if not is_eligible_for_version_or_revise(header):
        raise CommandError(
            "not-eligible-for-revision",
            "This decision cannot get a new revision: it must be Accepted or Rejected.",
        )
    if has_superseded_sibling(folder, config, filename_info.number):
        raise CommandError(
            "family-member-superseded", "A sibling decision in this family has already been superseded."
        )
    if has_pending_sibling(folder, config, filename_info.number):
        raise CommandError(
            "family-member-pending", "Another decision in this family is still unresolved (Proposed)."
        )

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)
    not_before = latest_header.date_update or latest_header.date_create
    if not_before is not None:
        validate_refdate_not_before(refdate, not_before)

    record = DecisionRecord(
        number=filename_info.number,
        title=header.title,
        version=header.version or 0,
        revision=(header.revision or 0) + 1,
        scope=header.scope,
        domain=header.domain,
        status_create="Proposed",
        date_create=refdate,
    )

    filename = build_filename(config, record)
    new_path = folder / filename
    if new_path.exists():
        raise CommandError("file-already-exists", f"File already exists: {filename}")

    content = build_header(config, record) + read_body(lines)
    atomic_write_text(new_path, content)

    return {"created": str(new_path), "status": config.statusnew}
