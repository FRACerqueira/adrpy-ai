"""`migrate` command: adds an adrpy header to existing,
hand-written decision files. Refuses outright if ANY file already has a
valid, non-migrated header (current-scheme, tool-created) -- migration is
a one-time operation for repositories with only manually-created
decisions. Rewrites only the header in place, and the filename is never
changed; the file's own content passes through byte-for-byte after the
new header, with the one confirmed exception (see the BOM-stripping
comment below) of a leading UTF-8 BOM, which is discarded rather than
carried through -- "preserved verbatim" refers to the body's own line
endings and bytes otherwise, not literally its every byte.

If the repository's own `migrationpattern` is empty, falls back to the
install-level config's own `migrationpattern` (see the `installconfig`
command; ADR002V01) when one is set there, and persists the found value
back into this repository's own `adr-config.adrplus`.
"""

import contextlib
import json
from dataclasses import asdict
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import STREAM_CHUNK_SIZE, atomic_write_chunks, atomic_write_text
from adrpy.core.fs import cleanup_orphaned_temp_files, scan_tree
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES, parse_repo_config
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import (
    DecisionRecord,
    build_header,
    has_header_shape,
    parse_header,
    read_header_lines_with_report,
)
from adrpy.core.install_config import read_install_config_text
from adrpy.core.lifecycle import resolve_target_and_config
from adrpy.core.naming import parse_any_filename
from adrpy.core.output import explain
from adrpy.core.text import is_ascii_digits
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, excluded_candidate_warning, orphan_cleanup_warning, retry_warning


def _stream_migrated_candidate(candidate_path, header_text):
    """ADR006V01: the candidate's own content has no schema-imposed size
    bound (unlike a header) -- the new header (already fully built,
    schema-bounded), followed by the candidate's own content streamed
    through unmodified in STREAM_CHUNK_SIZE-sized pieces straight from
    the source file into the destination temp file (via
    atomic_write_chunks), never assembled as one in-memory bytes object
    -- except any run of leading UTF-8 BOMs, stripped from the very first chunk
    only (see this module's own docstring)."""
    yield header_text.encode("utf-8")
    with Path(candidate_path).open("rb") as source:
        first_chunk = True
        while True:
            chunk = source.read(STREAM_CHUNK_SIZE)
            if not chunk:
                break
            if first_chunk:
                while chunk.startswith(b"\xef\xbb\xbf"):
                    chunk = chunk[3:]
                first_chunk = False
            yield chunk


def _carries_supersede_suffix(parsed, config):
    """True when a scanned name ends in a supersede suffix: a doubled
    separator, then only ASCII digits. parse_filename splits it off a
    current name (superseded_from); a legacy name is sliced by position,
    so there the suffix is still at the end of its title."""
    if parsed.superseded_from is not None:
        return True
    _head, separator, tail = (parsed.title or "").rpartition(config.separator * 2)
    return bool(separator) and is_ascii_digits(tail)


def describe():
    return {
        "name": "migrate",
        "summary": "Adds an adrpy-compliant header to existing, hand-written decision files.",
        "description": (
            "Adds an adrpy header with blank status cells (a migrated placeholder) to every hand-written "
            "decision file matching the repository's migrationpattern, which must be set in this repository's"
            " config or come from the install-level config's fallback; a fallback value is persisted into "
            "adr-config.adrplus first (reported as migrationpattern_persisted) and survives a later refusal, "
            "in which case no decision file is touched. It is a one-time step, refused as a whole when the "
            "tool already created a decision here, or when a scanned file has a damaged header, carries a "
            "supersede suffix, shares a number with another or cannot be read. Files are then migrated one by"
            " one; if any fails, data.results names every file's outcome."
        ),
        "arguments": [
            {"name": "path", "alias": "-p", "type": "string", "required": True, "description": "Repository root directory."},
        ],
        "failure_codes": build_failure_codes(
            {
                FailureCodes.TARGET_DIRECTORY_NOT_FOUND: "--path does not point to an existing directory.",
                FailureCodes.CONFIG_NOT_FOUND: "--path's own directory has no adr-config.adrplus.",
                FailureCodes.MIGRATION_PATTERN_NOT_CONFIGURED: "Both the repository's own migrationpattern and the install-level config's own fallback are empty.",
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER: "A candidate's own title (sourced from its raw legacy filename) contains '|', a line-break-like character, a filesystem-unsafe character, or consists entirely of whitespace/'_'/'-' -- a per-file failure, not a whole-batch abort.",
                FailureCodes.MIGRATION_SCAN_FAILED: "A candidate's own header could not even be read (permission denied or similar) -- refuses the whole run.",
                FailureCodes.MIGRATION_SCAN_INCOMPLETE: "A subdirectory under the decisions folder could not be scanned -- refuses the whole run.",
                FailureCodes.MIGRATION_SUCCESSOR_FILES_EXIST: "A scanned file already carries a supersede suffix (--NNN; data.files) -- a supersede chain is created by this tool only; refuses the whole run.",
                FailureCodes.MIGRATION_DUPLICATE_NUMBERS_EXIST: "Two or more scanned files share a number, version and revision (a missing revision counts as 0; data.files) -- refuses the whole run; rename them so each has its own.",
                FailureCodes.MIGRATION_INVALID_HEADERS_EXIST: "A scanned file looks like it carries this tool's header (a `|Adr-Plus ` row, an exact `|--|--|` line or a NUL byte in its first 12 lines) but it does not parse (data.files) -- refuses the whole run; repair or remove it by hand.",
                FailureCodes.ALREADY_TOOL_CREATED_ADRS_EXIST: "At least one scanned file already has a valid, non-migrated header -- refuses the whole run.",
                FailureCodes.NO_DECISIONS_FOUND: "No .md files matching a recognized naming scheme were found.",
                FailureCodes.NO_ELIGIBLE_FILES_TO_MIGRATE: "Every recognized file already has a header (migrated or tool-created) -- nothing needs migration.",
                FailureCodes.MIGRATION_WRITE_FAILED: "At least one candidate failed to write -- data.results names every candidate's own outcome.",
                FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
                FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
                FailureCodes.IO_ERROR: "A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
            },
            CONFIG_FAILURE_CODES,
        ),
    }


@contextlib.contextmanager
def _report_persisted_pattern(persisted, warnings):
    """The fallback migrationpattern persist-back commits before any
    candidate is looked at; every refusal after it must still say so
    (data.migrationpattern_persisted), or it reads as "nothing written".
    Likewise an interrupt once the per-file loop has started
    (`persisted["results"]`): the files already migrated are reported in
    data.results, so a re-run's smaller batch doesn't look like a loss."""
    try:
        yield
    except CommandError as error:
        if persisted["pattern"] is not None:
            error.data = {**(error.data or {}), "migrationpattern_persisted": persisted["pattern"]}
        raise
    except KeyboardInterrupt as error:
        data = {}
        if persisted["pattern"] is not None:
            data["migrationpattern_persisted"] = persisted["pattern"]
        if persisted.get("results") is not None:
            data["results"] = persisted["results"]
        if not data:
            raise
        raise CommandError("interrupted", "Interrupted (Ctrl+C).", data=data, warnings=list(warnings)) from error


def run(args):
    path = parse_flags(args, required=("path",), aliases={"p": "path"})["path"]
    target, config_path, config = resolve_target_and_config(path)

    folder = resolve_within(target, config.folderadr)
    warnings = []
    persisted = {"pattern": None}
    # Outside attach_warnings, so even an io-error it converts is covered.
    with _report_persisted_pattern(persisted, warnings), attach_warnings(warnings):
        # One walk of the folder feeds both the orphan sweep and the
        # candidate scan below.
        scan = scan_tree(folder) if folder.is_dir() else None
        if scan is not None:
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings, scan=scan))
            if warning:
                warnings.append(warning)

        # ADR002V01: the install-level fallback is only consulted when
        # the repository's own migrationpattern is empty.
        if not config.migrationpattern:
            fallback_text = read_install_config_text()
            fallback_pattern = parse_repo_config(fallback_text).migrationpattern if fallback_text else ""
            if not fallback_pattern:
                raise CommandError(
                    FailureCodes.MIGRATION_PATTERN_NOT_CONFIGURED,
                    "adr-config.adrplus has no migrationpattern configured, and the install-level "
                    "config (see installconfig) has none either.",
                    warnings=warnings,
                )
            # Persists the found value back into the repo's own config
            # now, as its own write, before any candidate is looked at:
            # the repository then carries the pattern it was migrated
            # with, and later commands read it directly, whatever this
            # run's outcome. Every result reports it
            # (migrationpattern_persisted), so a refusal below never
            # reads as "nothing written".
            merged = asdict(config)
            merged["migrationpattern"] = fallback_pattern
            merged_text = json.dumps(merged, indent=2, ensure_ascii=False)
            config = parse_repo_config(merged_text)  # re-validates the merged result; raises on failure
            attempts = atomic_write_text(config_path, merged_text)
            persisted["pattern"] = fallback_pattern
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

        entries = []  # (ParsedFileName, Path, HeaderParseResult)
        adulterated_files = []
        if scan is not None:
            # scan_tree keeps only files inside the folder's real
            # boundary (a junction or symlink escaping it is excluded).
            excluded = list(scan.excluded)
            for candidate in scan.markdown:
                found = parse_any_filename(candidate.name, config)
                if found is None:
                    continue
                _, parsed = found
                try:
                    # A byte a lossy decode replaced only matters if it
                    # breaks the header: then the file is refused as
                    # damaged (it keeps this tool's header shape, ASCII),
                    # never taken for a file with no header.
                    #
                    # Reads only the bounded header (parse_header never
                    # looks past it, and the write loop below copies
                    # body bytes through raw, untouched either way), not
                    # the whole candidate.
                    lines, _encoding_repaired = read_header_lines_with_report(candidate)
                except OSError as error:
                    # This scan-phase read must not run outside a
                    # try/except: a real failure here (permission
                    # denied, a locked file, a network-drive hiccup)
                    # would otherwise escape as a raw OSError,
                    # discarding the orphan-cleanup warning already
                    # appended above and skipping the deterministic
                    # per-file reporting the best-effort design
                    # otherwise guarantees.
                    raise CommandError(
                        FailureCodes.MIGRATION_SCAN_FAILED,
                        f"{candidate}: {error}",
                        data={"unreadable_file": str(candidate)},
                        warnings=warnings,
                    ) from error
                # Deliberately does not surface header.marker_label_
                # mismatches (ADR004V01) here -- this scan is a bulk
                # eligibility pass over every candidate, not a report
                # on one specific target file the way prepare's
                # own warning already covers.
                header = parse_header(lines, config)
                if not header.is_valid and has_header_shape(lines):
                    adulterated_files.append(str(candidate))
                entries.append((parsed, candidate, header))

            # Same as explore and the repository scan -- an excluded
            # candidate is reported, not dropped with zero signal.
            warning = excluded_candidate_warning(excluded)
            if warning:
                warnings.append(warning)
            # A subdirectory the scan could not list fails closed
            # instead of warning -- unlike explore's own best-effort
            # listing, this scan feeds already-tool-created-adrs-exist
            # below, a real safety decision (a hidden already-migrated
            # file could make that check silently answer "no" when the
            # true answer is "yes"). Same fail-closed treatment this
            # command already gives an unreadable FILE
            # (migration-scan-failed) -- a directory it can't enter is
            # the identical risk, just one level up.
            unreadable_dirs = list(scan.unreadable)
            if unreadable_dirs:
                raise CommandError(
                    FailureCodes.MIGRATION_SCAN_INCOMPLETE,
                    f"Cannot safely scan for existing decisions: {len(unreadable_dirs)} subdirectory/"
                    "subdirectories could not be scanned (permission denied or similar).",
                    data={"folder": str(folder), "unreadable": unreadable_dirs},
                    warnings=warnings,
                )

        if not entries:
            raise CommandError(
                FailureCodes.NO_DECISIONS_FOUND,
                "No .md files matching a recognized naming scheme were found.",
                warnings=warnings,
            )

        # A damaged header of this tool's is not "no header": migrating
        # would stamp a second one on top, and it may be the one
        # tool-created decision the check below needs to see.
        if adulterated_files:
            raise CommandError(
                FailureCodes.MIGRATION_INVALID_HEADERS_EXIST,
                f"{len(adulterated_files)} file(s) look like they carry this tool's header (a `|Adr-Plus ` row or "
                f"an exact `|--|--|` separator in the first 12 lines), or are not UTF-8 text at all (a NUL "
                f"byte there, e.g. UTF-16), and no header parses: "
                f"{', '.join(adulterated_files)}. Repair or remove them by hand, then run migrate again.",
                data={"files": adulterated_files},
                warnings=warnings,
            )

        if any(header.is_valid and not header.is_migrated for _, _, header in entries):
            raise CommandError(
                FailureCodes.ALREADY_TOOL_CREATED_ADRS_EXIST,
                "This repository already has decisions created by this tool; migration refuses to run.",
                warnings=warnings,
            )

        # A supersede chain is a concept this tool creates (decided by
        # the project owner): a file already claiming to be a
        # successor before migration (a --NNN suffix) is refused, so no
        # chain ever enters from outside.
        successor_files = [str(path) for parsed, path, _header in entries if _carries_supersede_suffix(parsed, config)]
        if successor_files:
            suffix = config.separator * 2
            raise CommandError(
                FailureCodes.MIGRATION_SUCCESSOR_FILES_EXIST,
                f"{len(successor_files)} file(s) already carry a supersede suffix ({suffix}NNN): "
                f"{', '.join(successor_files)}. A supersede chain is created by this tool only; rename them "
                "without the suffix, then migrate, and record the chain with supersede. If a title only looks "
                f"like a suffix (e.g. 'Release{suffix}2026'), rename the file so its title does not end in "
                f"{suffix}<digits>.",
                data={"files": successor_files},
                warnings=warnings,
            )

        # Two files with the same number, version and revision (a missing
        # revision counting as 0) would leave a repository every other
        # command refuses (duplicate-number): refused up front, like the
        # successor files above. Over every scanned file, so an
        # already-migrated one counts too.
        by_key = {}
        for parsed, candidate_path, _header in entries:
            by_key.setdefault((parsed.number, parsed.version, parsed.revision or 0), []).append(str(candidate_path))
        duplicate_files = sorted(path for paths in by_key.values() if len(paths) > 1 for path in paths)
        if duplicate_files:
            raise CommandError(
                FailureCodes.MIGRATION_DUPLICATE_NUMBERS_EXIST,
                f"{len(duplicate_files)} file(s) share a number, version and revision with another: "
                f"{', '.join(duplicate_files)}. Rename them so each has its own, then migrate.",
                data={"files": duplicate_files},
                warnings=warnings,
            )

        candidates = [
            (parsed, candidate_path)
            for parsed, candidate_path, header in entries
            if header.status_create is None and not header.is_migrated and not header.is_valid
        ]
        if not candidates:
            raise CommandError(FailureCodes.NO_ELIGIBLE_FILES_TO_MIGRATE, "No files need migration.", warnings=warnings)

        # Best-effort, not fail-fast -- one file's OSError (permission
        # denied, full disk) must not block the rest from migrating,
        # and the eventual failure response must carry a deterministic
        # per-candidate result (every file, migrated or failed) rather
        # than forcing the caller to infer what was never attempted.
        results = []
        persisted["results"] = results
        for parsed, candidate_path in candidates:
            try:
                title = (parsed.title or "").strip()
                # Unlike every other command's own title, this one is
                # sourced from a raw, untrusted legacy filename, sliced
                # positionally with zero character filtering
                # (naming.parse_legacy_filename) -- never validated
                # before, so a hostile legacy file's own name could embed
                # '|'/a line-break (forging the header table this write
                # is about to build) or a filesystem-unsafe character
                # (e.g. ':', an NTFS Alternate-Data-Stream separator,
                # which fails the rename below and leaves a permanent
                # orphan). Caught below alongside OSError/UnicodeError --
                # a per-file failure, not a whole-batch abort.
                reject_embedded_delimiter(title, "title")
                reject_filesystem_unsafe_title(title, "title")
                reject_title_with_no_case_transform_content(title, "title")
                record = DecisionRecord(number=parsed.number, title=title, version=0)
                header_text = build_header(config, record, migrated=True)
                # ADR006V01: streams the candidate's own content
                # straight from disk into the destination temp file --
                # never assembled as one in-memory bytes object (the
                # original content's own line endings, and anything
                # else about its bytes, still pass through completely
                # untouched; only the header text is new). A transient
                # PermissionError on EITHER the source read or the temp
                # write retries the whole temp write, the chunk
                # generator included, from one shared budget; the
                # commit that follows has its own and never reads the
                # source again. Each candidate is prepared and committed
                # on its own: best-effort per file.
                attempts = atomic_write_chunks(
                    candidate_path,
                    lambda: _stream_migrated_candidate(candidate_path, header_text),
                )
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(warning)
                results.append({"file": str(candidate_path), "status": "migrated", "error": None})
            except (OSError, UnicodeError, CommandError) as error:
                # UnicodeError (e.g. a UnicodeEncodeError from a title
                # containing a lone surrogate) is not an OSError, but is
                # just as plausible here as a real per-file failure --
                # catching only OSError would let it escape the whole
                # loop, discarding every result already collected.
                # CommandError is the title-validation check just above
                # (a hostile legacy filename) -- same per-file treatment,
                # not a whole-batch abort.
                results.append({"file": str(candidate_path), "status": "failed", "error": explain(error)})

        failed = [entry for entry in results if entry["status"] == "failed"]
        if failed:
            raise CommandError(
                FailureCodes.MIGRATION_WRITE_FAILED,
                f"{len(failed)} of {len(results)} file(s) failed to migrate.",
                data={"results": results},
                warnings=warnings,
            )

        migrated = [entry["file"] for entry in results]

    result = {"migrated": migrated, "warnings": warnings}
    if persisted["pattern"] is not None:
        result["migrationpattern_persisted"] = persisted["pattern"]
    return result
