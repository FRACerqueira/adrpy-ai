"""`supersede` command: marks an Accepted decision as Superseded and
creates its successor (harness Fase 7, item 5). Ported from
SupersedeCommandHandler.cs. The successor never copies the predecessor's
body (always starts from the config's default template) and its filename
suffix is unconditional, never a collision-disambiguator. `--open` is not
implemented (see `new.py`'s note -- same app-level config gap).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.lifecycle import (
    is_eligible_for_supersede,
    load_target,
    mark_superseded,
    next_number,
    parse_refdate,
    scan_decisions,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
)
from adrpy.core.naming import build_filename
from adrpy.core.security import reject_embedded_delimiter, resolve_within


def describe():
    return {
        "name": "supersede",
        "description": "Marks an Accepted decision as Superseded and creates its successor.",
        "arguments": [
            {"name": "file", "type": "string", "required": True, "description": "Path to the decision file."},
            {
                "name": "domain",
                "type": "string",
                "required": False,
                "description": "Domain for the successor; defaults to the predecessor's own value.",
            },
            {
                "name": "scope",
                "type": "string",
                "required": False,
                "description": "Scope for the successor; defaults to the predecessor's own value.",
            },
            {
                "name": "refdate",
                "type": "string",
                "required": False,
                "description": "Reference date (YYYY-MM-DD); defaults to today.",
            },
        ],
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("domain", "scope", "refdate"))
    config, root, path, filename_info, header, lines = load_target(flags["file"])

    if not is_eligible_for_supersede(header):
        raise CommandError(
            "not-eligible-for-supersede", "This decision cannot be superseded: it must currently be Accepted."
        )

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)
    not_before = header.date_update or header.date_create
    if not_before is not None:
        validate_refdate_not_before(refdate, not_before)

    # Unlike `new`, an omitted --scope/--domain defaults to the
    # predecessor's own current value, not empty.
    scope = flags["scope"] if "scope" in flags else (header.scope or "")
    domain = flags["domain"] if "domain" in flags else (header.domain or "")
    reject_embedded_delimiter(scope, "scope")
    reject_embedded_delimiter(domain, "domain")

    folder = resolve_within(root, config.folderadr)
    successor_number = next_number(scan_decisions(folder, config))

    successor = DecisionRecord(
        number=successor_number,
        # The successor's title comes from the predecessor's FILENAME
        # segment (already case-transformed), not its header's prose
        # title -- confirmed via live comparison: SupersedeCommandHandler
        # builds its new AdrRecord from `infoadr.Title` (AdrFileNameComponents'
        # own property, filename-derived), not `infoadr.Header.Title`.
        title=filename_info.title,
        version=1,
        revision=1 if config.lenrevision > 0 else None,
        scope=scope,
        domain=domain,
        status_create="Proposed",
        date_create=refdate,
        superseded=filename_info.number,
    )
    filename = build_filename(config, successor)
    successor_path = folder / filename
    if successor_path.exists():
        raise CommandError("file-already-exists", f"File already exists: {filename}")

    mark_superseded(path, config, lines, header, filename_info, successor_number, refdate)

    content = build_header(config, successor) + config.template
    atomic_write_text(successor_path, content)

    return {"predecessor": str(path), "created": str(successor_path), "status": config.statusnew}
