"""`migrate` command: adds an AdrPlus-compliant header to existing,
hand-written decision files (harness Fase 7, item 7). Ported from
MigrateCommandHandler.cs. Refuses outright if ANY file already has a
valid, non-migrated header (current-scheme, tool-created) -- migration is
a one-time operation for repositories with only manually-created
decisions. Rewrites only the header in place; the file's own content
(whatever it was) is preserved verbatim after it, and the filename is
never changed.

Known simplification, tracked as deferred (decision-log:
deferred--2026-09-15--migrate--no-install-level-fallback-for-migrationpattern.md):
the real tool falls back to an install-level shared default
`migrationpattern` when the repo's own is empty (`config --migrate` sets
that shared default, independent of any single repo) -- confirmed
against MigrateCommandHandler.cs:97-105. adrpy-ai has no install-level
config module at all (the `config` command that exists edits the repo's
own adr-config.adrplus directly, not a separate install-level layer) --
for now the repo's own `migrationpattern` must already be set; revisit
once that module exists.
"""

from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_bytes, cleanup_orphaned_temp_files, split_real_lines
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header, parse_header
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import is_within, resolve_within
from adrpy.core.warnings import attach_warnings, orphan_cleanup_warning, retry_warning


def describe():
    return {
        "name": "migrate",
        "description": (
            "Adds an AdrPlus-compliant header to existing, hand-written decision files. "
            "Requires the repository's migrationpattern to already be set (see the `config` command); "
            "fails with migration-pattern-not-configured otherwise -- true for any freshly-init'd repository. "
            "Best-effort per file: one file failing to write (e.g. a permission error) does not block the "
            "others. If any file fails, the whole command fails with migration-write-failed, whose `data.results` "
            "names every candidate file's own outcome (`migrated` or `failed`, with the error for the latter)."
        ),
        "arguments": [
            {"name": "path", "type": "string", "required": True, "description": "Repository root directory."},
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

    if not config.migrationpattern:
        raise CommandError(
            "migration-pattern-not-configured",
            "adr-config.adrplus has no migrationpattern configured.",
        )

    folder = resolve_within(target, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        entries = []  # (ParsedFileName, Path, HeaderParseResult)
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder))
            if warning:
                warnings.append(warning)
            for candidate in folder.rglob("*.md"):
                if not is_within(folder, candidate):
                    continue
                found = parse_any_filename(candidate.name, config)
                if found is None:
                    continue
                _, parsed = found
                try:
                    text = candidate.read_text(encoding="utf-8", errors="replace")
                except OSError as error:
                    # Mechanism-correctness audit round 3 (resilience
                    # finding #2a): this scan-phase read used to run
                    # entirely outside any try/except -- a real failure
                    # here (permission denied, a locked file, a network-
                    # drive hiccup) escaped as a raw OSError, discarding
                    # the orphan-cleanup warning already appended above
                    # and skipping the deterministic per-file reporting
                    # the best-effort redesign otherwise guarantees.
                    raise CommandError(
                        "migration-scan-failed",
                        f"{candidate}: {error}",
                        data={"unreadable_file": str(candidate)},
                        warnings=warnings,
                    ) from error
                lines = split_real_lines(text)
                entries.append((parsed, candidate, parse_header(lines, config)))

        if not entries:
            raise CommandError(
                "no-decisions-found",
                "No .md files matching a recognized naming scheme were found.",
                warnings=warnings,
            )

        if any(header.is_valid and not header.is_migrated for _, _, header in entries):
            raise CommandError(
                "already-tool-created-adrs-exist",
                "This repository already has decisions created by this tool; migration refuses to run.",
                warnings=warnings,
            )

        candidates = [
            (parsed, candidate_path)
            for parsed, candidate_path, header in entries
            if header.status_create is None and not header.is_migrated and not header.is_valid
        ]
        if not candidates:
            raise CommandError("no-eligible-files-to-migrate", "No files need migration.", warnings=warnings)

        # Design decision (2026-09-15): best-effort, not fail-fast -- one
        # file's OSError (permission denied, full disk) must not block the
        # rest from migrating, and the eventual failure response must
        # carry a deterministic per-candidate result (every file, migrated
        # or failed) rather than forcing the caller to infer what was
        # never attempted. Deliberate hardening beyond the original: the
        # real MigrateCommandHandler.cs's own per-file loop
        # (MigrateRepositoryAsync) has no try/catch either -- an exception
        # there propagates and loses even the partial `result` list it had
        # already built, so this isn't a fidelity requirement to preserve.
        results = []
        for parsed, candidate_path in candidates:
            try:
                # Raw bytes, not text: the original content's own line
                # endings (and anything else about its bytes) must pass
                # through completely untouched -- only the header text is
                # new. The one exception, confirmed live (fidelity audit
                # F7): the real tool discards a leading UTF-8 BOM when
                # reading, so it never appears in the migrated result --
                # pass it through here and it lands stranded in the middle
                # of the file, after the new header.
                raw_bytes = candidate_path.read_bytes()
                if raw_bytes.startswith(b"\xef\xbb\xbf"):
                    raw_bytes = raw_bytes[3:]
                record = DecisionRecord(number=parsed.number, title=(parsed.title or "").strip(), version=0)
                header_text = build_header(config, record, migrated=True)
                attempts = atomic_write_bytes(candidate_path, header_text.encode("utf-8") + raw_bytes)
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(warning)
                results.append({"file": str(candidate_path), "status": "migrated", "error": None})
            except (OSError, UnicodeError) as error:
                # UnicodeError (e.g. a UnicodeEncodeError from a title
                # containing a lone surrogate) is not an OSError, but is
                # just as plausible here as a real per-file failure --
                # mechanism-correctness audit round 3 (resilience finding
                # #2b): only catching OSError let it escape the whole
                # loop, discarding every result already collected.
                results.append({"file": str(candidate_path), "status": "failed", "error": str(error)})

        failed = [entry for entry in results if entry["status"] == "failed"]
        if failed:
            raise CommandError(
                "migration-write-failed",
                f"{len(failed)} of {len(results)} file(s) failed to migrate.",
                data={"results": results},
                warnings=warnings,
            )

        migrated = [entry["file"] for entry in results]

    return {"migrated": migrated, "warnings": warnings}
