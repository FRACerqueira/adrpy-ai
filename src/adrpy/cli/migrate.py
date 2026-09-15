"""`migrate` command: adds an AdrPlus-compliant header to existing,
hand-written decision files (harness Fase 7, item 7). Ported from
MigrateCommandHandler.cs. Refuses outright if ANY file already has a
valid, non-migrated header (current-scheme, tool-created) -- migration is
a one-time operation for repositories with only manually-created
decisions. Rewrites only the header in place; the file's own content
(whatever it was) is preserved verbatim after it, and the filename is
never changed.

Known simplification: the real tool falls back to an install-level
shared default `migrationpattern` when the repo's own is empty
(`config --migrate` sets that shared default, independent of any single
repo). adrpy-ai has no such install-level mechanism yet (Milestone 7 item
8, `config`, not implemented) -- for now the repo's own `migrationpattern`
must already be set; revisit once `config` exists.
"""

from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_bytes, split_real_lines
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header, parse_header
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import is_within, resolve_within


def describe():
    return {
        "name": "migrate",
        "description": "Adds an AdrPlus-compliant header to existing, hand-written decision files.",
        "arguments": [
            {"name": "path", "type": "string", "required": True, "description": "Repository root directory."},
        ],
    }


def run(args):
    path = parse_flags(args, required=("path",))["path"]
    target = Path(path)

    if not target.is_dir():
        raise CommandError("target-directory-not-found", f"Directory does not exist: {path}")

    config_path = target / "adr-config.adrplus"
    if not config_path.is_file():
        raise CommandError("config-not-found", f"No adr-config.adrplus found at: {config_path}")
    config = load_repo_config(config_path)

    if not config.migrationpattern:
        raise CommandError(
            "migration-pattern-not-configured",
            "adr-config.adrplus has no migrationpattern configured.",
        )

    folder = resolve_within(target, config.folderadr)
    entries = []  # (ParsedFileName, Path, HeaderParseResult)
    if folder.is_dir():
        for candidate in folder.rglob("*.md"):
            if not is_within(folder, candidate):
                continue
            found = parse_any_filename(candidate.name, config)
            if found is None:
                continue
            _, parsed = found
            lines = split_real_lines(candidate.read_text(encoding="utf-8", errors="replace"))
            entries.append((parsed, candidate, parse_header(lines, config)))

    if not entries:
        raise CommandError("no-decisions-found", "No .md files matching a recognized naming scheme were found.")

    if any(header.is_valid and not header.is_migrated for _, _, header in entries):
        raise CommandError(
            "already-tool-created-adrs-exist",
            "This repository already has decisions created by this tool; migration refuses to run.",
        )

    candidates = [
        (parsed, candidate_path)
        for parsed, candidate_path, header in entries
        if header.status_create is None and not header.is_migrated and not header.is_valid
    ]
    if not candidates:
        raise CommandError("no-eligible-files-to-migrate", "No files need migration.")

    migrated = []
    for parsed, candidate_path in candidates:
        # Raw bytes, not text: the original content's own line endings
        # (and anything else about its bytes) must pass through completely
        # untouched -- only the header text is new.
        raw_bytes = candidate_path.read_bytes()
        record = DecisionRecord(number=parsed.number, title=(parsed.title or "").strip(), version=0)
        header_text = build_header(config, record, migrated=True)
        atomic_write_bytes(candidate_path, header_text.encode("utf-8") + raw_bytes)
        migrated.append(str(candidate_path))

    return {"migrated": migrated}
