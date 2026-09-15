"""`explore` command: read-only inventory of every decision file (harness
Fase 7, item 3). Declares (Fase 6 checklist): recognizes BOTH naming
schemes via `parse_any_filename` -- a file matching neither still appears
in the report, never dropped silently.
"""

from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import split_real_lines
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import parse_header
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import is_within, resolve_within


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
    path = parse_flags(args, required=("path",), aliases={"p": "path"})["path"]
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
            if not is_within(folder, candidate):
                continue
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

    # Usability audit round 3 (finding #5): every mutating command's
    # result carries "warnings" unconditionally, even when empty (see
    # config's own read-mode) -- explore never generates one (it's
    # read-only), but omitting the key entirely broke a generic wrapper
    # that assumed `data["warnings"]` always exists across all commands.
    return {"decisions": entries, "warnings": []}


def _build_entry(path, config):
    found = parse_any_filename(path.name, config)
    scheme, parsed = found if found else (None, None)

    # Fase 4: tolerate invalid bytes rather than raising, mirroring the
    # original's confirmed-live behavior (see the Fase 4 commit).
    raw_bytes = path.read_bytes()
    try:
        text = raw_bytes.decode("utf-8")
        encoding_repaired = False
    except UnicodeDecodeError:
        text = raw_bytes.decode("utf-8", errors="replace")
        encoding_repaired = True
    header = parse_header(split_real_lines(text), config)

    return {
        "filename": path.name,
        "path": str(path),
        "scheme": scheme,
        "number": parsed.number if parsed else 0,
        "version": parsed.version if parsed else 0,
        "revision": parsed.revision if parsed else None,
        "title": parsed.title if parsed else None,
        "header": {
            "is_valid": header.is_valid,
            "is_migrated": header.is_migrated,
            "scope": header.scope,
            "domain": header.domain,
            "status_create": header.status_create,
            "date_create": header.date_create.isoformat() if header.date_create else None,
            "status_update": header.status_update,
            "date_update": header.date_update.isoformat() if header.date_update else None,
            "status_change": header.status_change,
            "date_change": header.date_change.isoformat() if header.date_change else None,
            "superseded_by_file": header.superseded_by_file,
            # Observability audit: tells the caller this specific file's
            # bytes were lossy-decoded (Fase 4 tolerance) -- explore is a
            # read-only report, the natural place for this visibility.
            "encoding_repaired": encoding_repaired,
        },
    }
