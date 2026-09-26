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
from dataclasses import asdict
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import STREAM_CHUNK_SIZE, normalize_newlines
from adrpy.core.fs import (
    cleanup_orphaned_temp_files,
    cleanup_orphaned_temp_files_for,
    commit_write,
    is_zero_bytes,
    landed_after_failure,
    prepare_write,
    scan_tree,
    write_landed,
)
from adrpy.core.config import (
    SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES,
    parse_repo_config,
    reject_overlapping_migration_pattern,
    serialize_repo_config,
)
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import (
    DecisionRecord,
    build_header,
    has_header_shape,
    parse_header,
    read_header_lines_with_report,
)
from adrpy.core.install_config import read_install_config_text
from adrpy.core.lifecycle import (
    PATTERN_ADVICE_AFTER_MIGRATE,
    has_valid_header,
    legacy_pattern_warnings,
    resolve_target_and_config,
)
from adrpy.core.naming import (
    REWRITE_TOO_LONG_REMEDY,
    migration_pattern_overlap,
    parse_any_filename,
    reject_too_long_filename,
)
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
    core/fs.prepare_write), never assembled as one in-memory bytes object
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


def _migrated_with_the_pattern(scan, config):
    """Whether a legacy-scheme file of `scan` already has a valid header:
    the same count that blocks a migrationpattern change
    (core/lifecycle.has_valid_header)."""
    if scan is None:
        return False
    for candidate in scan.markdown:
        found = parse_any_filename(candidate.name, config)
        if found is not None and found[0] == "legacy" and has_valid_header(candidate, config):
            return True
    return False


def _existing_headers(scan, config):
    """(damaged, not_written_by_migrate): the files of `scan` recognized
    under `config` whose header has this tool's shape but does not parse,
    and those whose header parses and is not migrate's placeholder
    (written by AdrPlus or adrpy). A file that cannot be read is left to
    the full scan in run(), which refuses it."""
    damaged, not_written_by_migrate = [], []
    for candidate in scan.markdown:
        if parse_any_filename(candidate.name, config) is None:
            continue
        try:
            lines, _encoding_repaired = read_header_lines_with_report(candidate)
        except OSError:
            continue
        header = parse_header(lines, config)
        if not header.is_valid and has_header_shape(lines):
            damaged.append(str(candidate))
        elif header.is_valid and not header.is_migrated:
            not_written_by_migrate.append(str(candidate))
    return damaged, sorted(not_written_by_migrate)


def _refuse_damaged_headers(files, warnings):
    raise CommandError(
        FailureCodes.MIGRATION_INVALID_HEADERS_EXIST,
        f"{len(files)} file(s) look like they carry this tool's header (a `|Adr-Plus ` row or "
        f"an exact `|--|--|` separator in the first 12 lines), or are not UTF-8 text at all (a NUL "
        f"byte there, e.g. UTF-16), and no header parses: "
        f"{', '.join(files)}. Repair or remove them by hand, then run migrate again.",
        data={"files": files},
        warnings=warnings,
    )


def _refuse_headers_migrate_did_not_write(files, warnings):
    raise CommandError(
        FailureCodes.ALREADY_TOOL_CREATED_ADRS_EXIST,
        f"{len(files)} file(s) already have a valid header migrate did not write (AdrPlus or adrpy): "
        f"{', '.join(files)}. migrate only runs on a repository with no such header: give each remaining "
        "file without one a header by hand (copy it from one of these), or rename or remove it.",
        data={"files": files},
        warnings=warnings,
    )


def describe():
    return {
        "name": "migrate",
        "summary": "Adds an adrpy-compliant header to existing, hand-written decision files.",
        "description": (
            "Adds an adrpy header with blank status cells (a migrated placeholder) to every hand-written "
            "decision file matching the repository's migrationpattern, which must be set in this repository's"
            " config or come from the install-level config's fallback, and must not read part of a name twice"
            " (its T inside its N/V/R/P range, or two of those ranges overlapping: config-migrationpattern-invalid,"
            " refused before anything is written, a fallback before it is persisted; once a decision was migrated"
            " with the repository's own, the guard keeps it and migrate finishes with it, with a warning that the"
            " titles begin with part of the number). It is a one-time step, refused as a whole"
            " when a file already has a valid header migrate did not write (checked first, before anything is "
            "written); a fallback value is then persisted into adr-config.adrplus (reported as "
            "migrationpattern_persisted) and survives a later refusal, in which case no decision file is "
            "touched. It is also refused as a whole when a scanned file has a damaged header, carries a "
            "supersede suffix, shares a number with another or cannot be read. Files are then migrated one by"
            " one; if any fails, data.results names every file's outcome, and a re-run migrates the files still "
            "without a header. `adrpy explore --path . --migrationpattern <pattern>` previews what a pattern "
            "reads from each name (number, version, title) without writing anything; `warnings` flags a "
            "title that starts with a separator or a number far above the others (a likely wrong pattern)."
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
                FailureCodes.ALREADY_TOOL_CREATED_ADRS_EXIST: "At least one scanned file already has a valid header migrate did not write (AdrPlus or adrpy; data.files) -- refuses the whole run, checked before migrationpattern is needed or persisted from the fallback; the files still without a header get one by hand.",
                FailureCodes.NO_DECISIONS_FOUND: "No .md files matching a recognized naming scheme were found.",
                FailureCodes.NO_ELIGIBLE_FILES_TO_MIGRATE: "Every recognized file already has a header (migrated or tool-created), or is empty (0 bytes, skipped with a warning) -- nothing needs migration.",
                FailureCodes.MIGRATION_WRITE_FAILED: "At least one candidate failed to write -- data.results names every candidate's own outcome. A name longer than the 234 bytes this tool can rewrite fails that way too, with nothing written to it (its error says to rename it by hand).",
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
    data.results, so a re-run's smaller batch doesn't look like a loss.
    A file whose write was interrupted right after the replace that
    committed it (`persisted["in_flight"]`, decided from the disk by
    core/fs.write_landed) counts as migrated."""
    try:
        yield
    except CommandError as error:
        if persisted["pattern"] is not None:
            error.data = {**(error.data or {}), "migrationpattern_persisted": persisted["pattern"]}
        raise
    except BaseException as error:
        # Ctrl+C or anything unexpected (as core/lifecycle.commit_in_order
        # does): what was already migrated is reported, not lost.
        in_flight = persisted.get("in_flight")
        if in_flight is not None and landed_after_failure(in_flight):
            _record_migrated(persisted["results"], in_flight.path)
        data = {}
        if persisted["pattern"] is not None:
            data["migrationpattern_persisted"] = persisted["pattern"]
        if persisted.get("results") is not None:
            data["results"] = persisted["results"]
        if not data:
            raise
        cause = "Ctrl+C" if isinstance(error, KeyboardInterrupt) else explain(error)
        raise CommandError("interrupted", f"Interrupted ({cause}).", data=data, warnings=list(warnings)) from error


def _record_migrated(results, candidate_path):
    """Adds `candidate_path` to `results` as migrated, once."""
    entry = {"file": str(candidate_path), "status": "migrated", "error": None}
    if entry not in results:
        results.append(entry)


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
        # The config's own temps (from an interrupted migrationpattern
        # persist-back) sit at the repository root, outside that sweep.
        warning = orphan_cleanup_warning(cleanup_orphaned_temp_files_for([config_path], warnings=warnings))
        if warning:
            warnings.append(warning)

        # Before migrationpattern is even needed (or persisted from the
        # fallback): a repository AdrPlus or adrpy already manages is
        # told so (a damaged header first, as below), never sent to
        # configure a pattern first. The same checks run again below,
        # over the names a fallback pattern adds.
        if scan is not None:
            damaged, tool_created = _existing_headers(scan, config)
            if damaged:
                _refuse_damaged_headers(damaged, warnings)
            if tool_created:
                _refuse_headers_migrate_did_not_write(tool_created, warnings)

        # A pattern that reads part of a name twice is refused before
        # anything is written: the repository's own here, the fallback
        # before it is persisted. Once a decision was migrated with the
        # repository's own, the migrationpattern guard keeps it from
        # changing, so migrate finishes with it and says so instead.
        if config.migrationpattern:
            overlap = migration_pattern_overlap(config.migrationpattern)
            if overlap is not None:
                if not _migrated_with_the_pattern(scan, config):
                    reject_overlapping_migration_pattern(config.migrationpattern)
                warnings.append(
                    f"migrationpattern '{config.migrationpattern}' reads part of a name twice: {overlap}. "
                    "Decisions were already migrated with it, so it can no longer change and migrate uses "
                    "it: the titles it reads begin with part of the number -- correct each migrated "
                    "file's `File title md` row by hand."
                )

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
            reject_overlapping_migration_pattern(fallback_pattern)
            # Persists the found value back into the repo's own config
            # now, as its own write, before any candidate is looked at:
            # the repository then carries the pattern it was migrated
            # with, and later commands read it directly, whatever this
            # run's outcome. Every result reports it
            # (migrationpattern_persisted), so a refusal below never
            # reads as "nothing written".
            merged = asdict(config)
            merged["migrationpattern"] = fallback_pattern
            merged_text = serialize_repo_config(merged)
            config = parse_repo_config(merged_text)  # re-validates the merged result; raises on failure
            prepared = prepare_write(config_path, normalize_newlines(merged_text).encode("utf-8"))
            try:
                attempts = prepared.attempts + commit_write(prepared) - 1
                persisted["pattern"] = fallback_pattern
            except BaseException:
                # Interrupted right after the replace that committed it.
                if landed_after_failure(prepared):
                    persisted["pattern"] = fallback_pattern
                raise
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

        entries = []  # (ParsedFileName, Path, HeaderParseResult)
        adulterated_files = []
        # 0-byte files, never a decision to migrate: with a current-scheme
        # name, an interrupted create's name reservation; with a legacy
        # one (the tool never creates such a name), the user's file.
        empty_files = []
        empty_legacy_files = []
        if scan is not None:
            # scan_tree keeps only files inside the folder's real
            # boundary (a junction or symlink escaping it is excluded).
            excluded = list(scan.excluded)
            for candidate in scan.markdown:
                found = parse_any_filename(candidate.name, config)
                if found is None:
                    continue
                scheme, parsed = found
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
                if not lines and is_zero_bytes(candidate):
                    (empty_legacy_files if scheme == "legacy" else empty_files).append(candidate)
                    continue
                header = parse_header(lines, config)
                if not header.is_valid and has_header_shape(lines):
                    adulterated_files.append(str(candidate))
                entries.append((parsed, candidate, header))

            if empty_files:
                warnings.append(
                    f"{len(empty_files)} empty (0-byte) file(s) skipped, most likely left by an interrupted "
                    f"create: remove them. {', '.join(sorted(str(path) for path in empty_files))}."
                )
            if empty_legacy_files:
                warnings.append(
                    f"{len(empty_legacy_files)} empty (0-byte) file(s) with a legacy-scheme name skipped: this tool "
                    "never creates such a name, so they are the user's -- ask before removing them. They are not "
                    "migrated while empty, and check reports them as no-header until they have content (then run "
                    f"migrate again). {', '.join(sorted(str(path) for path in empty_legacy_files))}."
                )

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

        if not entries and not empty_files and not empty_legacy_files:
            raise CommandError(
                FailureCodes.NO_DECISIONS_FOUND,
                "No .md files matching a recognized naming scheme were found.",
                warnings=warnings,
            )

        # A damaged header of this tool's is not "no header": migrating
        # would stamp a second one on top, and it may be the one
        # tool-created decision the check below needs to see.
        if adulterated_files:
            _refuse_damaged_headers(adulterated_files, warnings)

        tool_created = sorted(str(path) for _, path, header in entries if header.is_valid and not header.is_migrated)
        if tool_created:
            _refuse_headers_migrate_did_not_write(tool_created, warnings)

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

        # By name, not in the order the folder lists them (by name on NTFS
        # and APFS, in hash order on ext4): the results, and what an
        # interrupt leaves migrated, are the same on every system.
        candidates = sorted(
            (
                (parsed, candidate_path)
                for parsed, candidate_path, header in entries
                if header.status_create is None and not header.is_migrated and not header.is_valid
            ),
            key=lambda item: item[1].relative_to(folder).parts,
        )
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
                reject_too_long_filename(candidate_path.name, REWRITE_TOO_LONG_REMEDY)
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
                prepared = prepare_write(
                    candidate_path,
                    lambda: _stream_migrated_candidate(candidate_path, header_text),
                )
                persisted["in_flight"] = prepared
                try:
                    attempts = prepared.attempts + commit_write(prepared) - 1
                except (OSError, UnicodeError):
                    if not write_landed(prepared):
                        raise
                    attempts = 1
                _record_migrated(results, candidate_path)
                persisted["in_flight"] = None
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(warning)
            except (OSError, UnicodeError, CommandError) as error:
                # UnicodeError (e.g. a UnicodeEncodeError from a title
                # containing a lone surrogate) is not an OSError, but is
                # just as plausible here as a real per-file failure --
                # catching only OSError would let it escape the whole
                # loop, discarding every result already collected.
                # CommandError is the title-validation check just above
                # (a hostile legacy filename) -- same per-file treatment,
                # not a whole-batch abort.
                persisted["in_flight"] = None
                results.append({"file": str(candidate_path), "status": "failed", "error": explain(error)})

        warnings.extend(
            legacy_pattern_warnings(
                [
                    {"file": str(path), "number": parsed.number, "title": (parsed.title or "").strip()}
                    for parsed, path in candidates
                ],
                PATTERN_ADVICE_AFTER_MIGRATE,
            )
        )
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
