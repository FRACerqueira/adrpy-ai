"""`explore` command: read-only inventory of every decision file (harness
Fase 7, item 3). Declares (Fase 6 checklist): recognizes BOTH naming
schemes via `parse_any_filename` -- a file matching neither still appears
in the report, never dropped silently.
"""

from pathlib import Path

from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.header import parse_header
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import resolve_within


def describe():
    return {
        "name": "explore",
        "description": "Lists every decision file in the repository, recognized or not.",
        "arguments": [
            {
                "name": "path",
                "type": "string",
                "required": True,
                "description": "Repository root directory (must contain adr-config.adrplus).",
            },
        ],
    }


def run(args):
    path = _parse_args(args)
    target = Path(path)

    if not target.is_dir():
        raise CommandError("target-directory-not-found", f"Directory does not exist: {path}")

    config_path = target / "adr-config.adrplus"
    if not config_path.is_file():
        raise CommandError("config-not-found", f"No adr-config.adrplus found at: {config_path}")

    config = load_repo_config(config_path)
    folder = resolve_within(target, config.folderadr)

    entries = []
    if folder.is_dir():
        for candidate in folder.rglob("*.md"):
            entries.append(_build_entry(candidate, config))

    # Mirrors AdrService.ReadAllAdr's real sort order:
    # OrderByDescending(IsValid).ThenBy(IsMigrated).ThenByDescending(Number)
    # .ThenByDescending(Version).ThenByDescending(Revision ?? 0)
    entries.sort(
        key=lambda entry: (
            -int(entry["header"]["is_valid"]),
            int(entry["header"]["is_migrated"]),
            -entry["number"],
            -entry["version"],
            -(entry["revision"] or 0),
        )
    )

    return {"decisions": entries}


def _parse_args(args):
    path = None
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--path":
            i += 1
            if i >= len(args):
                raise UsageError("--path requires a value")
            path = args[i]
        else:
            raise UsageError(f"Unknown argument: {token}")
        i += 1
    if not path:
        raise UsageError("Missing required argument: --path")
    return path


def _build_entry(path, config):
    found = parse_any_filename(path.name, config)
    scheme, parsed = found if found else (None, None)

    # Fase 4: tolerate invalid bytes rather than raising, mirroring the
    # original's confirmed-live behavior (see the Fase 4 commit).
    text = path.read_text(encoding="utf-8", errors="replace")
    header = parse_header(text.splitlines(), config)

    return {
        "filename": path.name,
        "scheme": scheme,
        "number": parsed.number if parsed else 0,
        "version": parsed.version if parsed else 0,
        "revision": parsed.revision if parsed else None,
        "title": parsed.title if parsed else None,
        "header": {
            "is_valid": header.is_valid,
            "is_migrated": header.is_migrated,
            "status_create": header.status_create,
            "date_create": header.date_create.isoformat() if header.date_create else None,
            "status_update": header.status_update,
            "date_update": header.date_update.isoformat() if header.date_update else None,
            "status_change": header.status_change,
            "date_change": header.date_change.isoformat() if header.date_change else None,
            "superseded_by_file": header.superseded_by_file,
        },
    }
