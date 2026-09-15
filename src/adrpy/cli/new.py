"""`new` command: creates a new decision with status Proposed (harness
Fase 7, item 2). Ported from NewAdrCommandHandler.cs. `--open` (launches an
external editor via the app-level `comandopenadr` setting) is not
implemented -- that setting lives in the app-level config this project
hasn't built yet (Milestone 7 item 6, `config`); revisit then.
"""

from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.lifecycle import (
    find_by_unique_title,
    next_number,
    parse_refdate,
    scan_decisions,
    validate_refdate_not_in_future,
)
from adrpy.core.naming import build_filename
from adrpy.core.security import reject_embedded_delimiter, resolve_within


def describe():
    return {
        "name": "new",
        "description": "Creates a new decision with status Proposed.",
        "arguments": [
            {"name": "path", "type": "string", "required": True, "description": "Repository root directory."},
            {"name": "title", "type": "string", "required": True, "description": "Title of the new decision."},
            {"name": "domain", "type": "string", "required": False, "description": "Optional domain header field."},
            {"name": "scope", "type": "string", "required": False, "description": "Optional scope header field."},
            {
                "name": "refdate",
                "type": "string",
                "required": False,
                "description": "Reference date (YYYY-MM-DD); defaults to today.",
            },
        ],
    }


def run(args):
    flags = parse_flags(args, required=("path", "title"), optional=("domain", "scope", "refdate"))
    target = Path(flags["path"])
    title = flags["title"]
    domain = flags.get("domain", "")
    scope = flags.get("scope", "")

    if not target.is_dir():
        raise CommandError("target-directory-not-found", f"Directory does not exist: {flags['path']}")

    config_path = target / "adr-config.adrplus"
    if not config_path.is_file():
        raise CommandError("config-not-found", f"No adr-config.adrplus found at: {config_path}")

    config = load_repo_config(config_path)

    reject_embedded_delimiter(title, "title")
    reject_embedded_delimiter(domain, "domain")
    reject_embedded_delimiter(scope, "scope")

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)

    folder = resolve_within(target, config.folderadr)
    decisions = scan_decisions(folder, config)

    existing = find_by_unique_title(title, config, decisions)
    if existing is not None:
        raise CommandError(
            "title-already-exists", f"A decision with this title already exists: {existing.name}"
        )

    record = DecisionRecord(
        number=next_number(decisions),
        title=title,
        version=1,
        revision=1 if config.lenrevision > 0 else None,
        scope=scope,
        domain=domain,
        status_create="Proposed",
        date_create=refdate,
    )

    filename = build_filename(config, record)
    file_path = resolve_within(folder, filename)
    if file_path.exists():
        raise CommandError("file-already-exists", f"File already exists: {filename}")

    content = build_header(config, record) + config.template
    atomic_write_text(file_path, content)

    return {"created": str(file_path), "status": config.statusnew}
