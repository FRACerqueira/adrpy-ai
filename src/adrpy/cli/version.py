"""`version` command: creates a new major version of an Accepted/Rejected
decision (harness Fase 7, item 6). Ported from VersionCommandHandler.cs.
`--open` is not implemented (see `new.py`'s note).
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
from adrpy.core.security import reject_embedded_delimiter, resolve_within


def describe():
    return {
        "name": "version",
        "description": "Creates a new major version of an Accepted/Rejected decision.",
        "arguments": [
            {"name": "file", "type": "string", "required": True, "description": "Path to the decision file."},
            {
                "name": "domain",
                "type": "string",
                "required": False,
                "description": "Domain for the new version; defaults to the latest version's own value.",
            },
            {
                "name": "scope",
                "type": "string",
                "required": False,
                "description": "Scope for the new version; defaults to the latest version's own value.",
            },
            {
                "name": "refdate",
                "type": "string",
                "required": False,
                "description": "Reference date (YYYY-MM-DD); defaults to today.",
            },
            {
                "name": "empty",
                "type": "boolean",
                "required": False,
                "description": "Start from the default template instead of carrying the source's content forward.",
            },
        ],
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("domain", "scope", "refdate"), switches=("empty",))
    config, root, path, filename_info, header, lines = load_target(flags["file"])
    folder = resolve_within(root, config.folderadr)

    latest = latest_in_family(folder, config, filename_info.number)
    if latest is None:
        raise CommandError("family-not-found", "Could not resolve this decision's own family.")
    latest_parsed, latest_header, latest_path = latest

    if len(str(latest_parsed.version + 1)) > config.lenversion:
        raise CommandError(
            "lenversion-too-small-for-new-version",
            f"New version {latest_parsed.version + 1} does not fit in lenversion={config.lenversion}.",
        )

    if latest_path.resolve() != path.resolve():
        # Branching a new version off an older member is allowed only when
        # the actual latest was Rejected -- the harness's own documented
        # exception (Fase 7 item 6).
        allowed = latest_header.status_update == "Rejected" and (
            latest_parsed.version > filename_info.version
            or (
                latest_parsed.version == filename_info.version
                and (latest_parsed.revision or 0) > (filename_info.revision or 0)
            )
        )
        if not allowed:
            raise CommandError(
                "not-latest-version", "This decision is not the latest version/revision in its family."
            )

    if not is_eligible_for_version_or_revise(header):
        raise CommandError(
            "not-eligible-for-version",
            "This decision cannot get a new version: it must be Accepted or Rejected.",
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

    # Unlike `new`, an omitted --scope/--domain defaults to the LATEST
    # family member's own current value, not empty -- and not the
    # branch-target's value either, when branching off an older Rejected
    # sibling (confirmed in VersionCommandHandler.cs).
    scope = flags["scope"] if "scope" in flags else (latest_header.scope or "")
    domain = flags["domain"] if "domain" in flags else (latest_header.domain or "")
    reject_embedded_delimiter(scope, "scope")
    reject_embedded_delimiter(domain, "domain")

    template = config.template if flags.get("empty") else read_body(lines)

    record = DecisionRecord(
        number=filename_info.number,
        title=header.title,
        version=latest_parsed.version + 1,
        revision=1 if config.lenrevision > 0 else None,
        scope=scope,
        domain=domain,
        status_create="Proposed",
        date_create=refdate,
    )

    filename = build_filename(config, record)
    new_path = folder / filename
    if new_path.exists():
        raise CommandError("file-already-exists", f"File already exists: {filename}")

    content = build_header(config, record) + template
    atomic_write_text(new_path, content)

    return {"created": str(new_path), "status": config.statusnew}
