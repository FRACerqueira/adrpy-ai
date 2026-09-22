"""`migrate` command: adds an AdrPlus-compliant header to existing,
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
back into this repository's own `adr-config.adrplus` as part of the same
locked write -- matching the reference tool's own confirmed behavior. The
fallback lookup and persist-back
happen AFTER the repository lock is acquired and the config is re-read
fresh (ADR001's freshness principle), not from the pre-lock read, so a
concurrent direct edit of the repo's own migrationpattern is never
silently overwritten by a stale fallback decision.
"""

import json
from dataclasses import asdict
from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import STREAM_CHUNK_SIZE, atomic_write_chunks, atomic_write_text, cleanup_orphaned_temp_files
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES, parse_repo_config
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import DecisionRecord, build_header, parse_header
from adrpy.core.install_config import read_install_config_text
from adrpy.core.lifecycle import read_header_lines_with_report, resolve_target_and_config, verify_folderadr_unchanged_since_lock
from adrpy.core.lock import SHARED_FAILURE_CODES as LOCK_FAILURE_CODES, LockLostError, acquire_repo_lock
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import (
    find_unreadable_subdirectories,
    is_within,
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, excluded_candidate_warning, orphan_cleanup_warning, retry_warning


def _stream_migrated_candidate(candidate_path, header_text, lock):
    """ADR006V01: the candidate's own content has no schema-imposed size
    bound (unlike a header) -- the new header (already fully built,
    schema-bounded), followed by the candidate's own content streamed
    through unmodified in STREAM_CHUNK_SIZE-sized pieces straight from
    the source file into the destination temp file (via
    atomic_write_chunks), never assembled as one in-memory bytes object
    -- except a leading UTF-8 BOM, stripped from the very first chunk
    only, matching the reference tool's own confirmed behavior (see this
    module's own docstring).

    `lock.verify_still_held()` runs again as the very last thing here,
    right before this generator exhausts (i.e. right before
    atomic_write_chunks proceeds to its committing os.replace) -- the
    per-candidate pre-call check in the loop below only proves the lock
    was held before THIS candidate's streamed read/write began, and a
    large legacy file can now take genuinely non-trivial time to stream.
    Same reasoning, and the same live-confirmed regression, as
    core/lifecycle.py's _rewrite_with_streamed_body."""
    yield header_text.encode("utf-8")
    with Path(candidate_path).open("rb") as source:
        first_chunk = True
        while True:
            chunk = source.read(STREAM_CHUNK_SIZE)
            if not chunk:
                break
            if first_chunk:
                if chunk.startswith(b"\xef\xbb\xbf"):
                    chunk = chunk[3:]
                first_chunk = False
            yield chunk
    lock.verify_still_held()


def describe():
    return {
        "name": "migrate",
        "summary": "Adds an adrpy-compliant header to existing, hand-written decision files.",
        "description": (
            "Adds an AdrPlus-compliant header to existing, hand-written decision files. "
            "May fail with target-directory-not-found if --path does not point to an existing directory, "
            "or config-not-found if that directory has no adr-config.adrplus -- no file is touched either "
            "way. "
            "Requires the repository's migrationpattern to be set, either directly (see the `config` "
            "command) or via the install-level config's own fallback (see the `installconfig` command); "
            "fails with migration-pattern-not-configured only when both are empty -- true for any "
            "freshly-init'd repository with no install-level config set up either. "
            "When the fallback supplies the value, it is also persisted back into this repository's own "
            "adr-config.adrplus -- inside the same repository lock as the rest of this command, but as an "
            "earlier, independent write, not atomically bundled with the migration itself: it commits "
            "before the scan/eligibility checks below run, and survives even if this same call goes on "
            "to fail one of them (migration-scan-failed/-incomplete/-unreliable-encoding, "
            "no-decisions-found, already-tool-created-adrs-exist, no-eligible-files-to-migrate) -- those "
            "refusals mean no DECISION file was touched, not that adr-config.adrplus itself wasn't. "
            "Subsequent commands see the persisted value directly, without consulting the install-level "
            "config again, regardless of whether this particular run went on to succeed. "
            "Best-effort per file: one file failing to write (e.g. a permission error) does not block the "
            "others. If any file fails, the whole command fails with migration-write-failed, whose `data.results` "
            "names every candidate file's own outcome (`migrated` or `failed`, with the error for the latter). "
            "A candidate whose title -- sourced from the raw legacy filename itself, unlike every other "
            "command's own title -- carries '|', a line-break-like character, a filesystem-unsafe "
            "character (`<>:\"/\\|?*` or a control character; the new header this write is about to build "
            "would otherwise embed it verbatim, or -- for the filesystem-unsafe set -- this file's own "
            "existing name already avoided them, since none of them survive as a real filename component "
            "on this platform), or consists entirely of whitespace/'_'/'-' (e.g. a legacy title segment of "
            "'---') -- the case-transform step falls back to echoing such a value raw, which can collide "
            "with the filename's own separator and produce a file the tool can never recognize again -- is "
            "one such per-file failure (field-contains-forbidden-character), never a silent write. "
            "If the repository lock is lost partway through (a different process reclaimed it), the whole run "
            "aborts immediately instead of continuing unprotected, with migration-lock-lost -- its own "
            "`data.results` names only the candidates actually attempted before the loss; none after. "
            "May instead fail with repository-locked if the lock could not be acquired in time before any "
            "file is touched, or with folderadr-changed-after-lock-acquired if a concurrent config change "
            "moved folderadr while this call was acquiring the lock -- no file is touched either way; retry. "
            "This is a one-time, largely irreversible operation for repositories with only manually-created "
            "decisions: refuses the ENTIRE run with already-tool-created-adrs-exist -- no decision file is "
            "touched -- if "
            "even ONE scanned file already has a valid, non-migrated header (i.e. this repository has decisions "
            "this tool itself already created). "
            "Refuses the whole run with migration-scan-unreliable-encoding, naming every affected file in "
            "`data.unreliable_files`, if any scanned file's content isn't valid UTF-8 -- a lossy decode there "
            "can't be trusted for the already-tool-created-adrs-exist safety check above or for candidate "
            "eligibility. Its structurally identical sibling, migration-scan-failed (`data.unreadable_file` "
            "names the one file), refuses the whole run the same way if a scanned file's header can't even "
            "be read (permission denied or similar) -- same scan phase, same all-or-nothing semantics, a "
            "real OSError instead of a lossy decode. Also refuses with migration-scan-incomplete "
            "(`data.unreadable` names the subdirectories) if a subdirectory under the decisions folder "
            "couldn't be scanned at all -- a hidden already-migrated file inside it could make the "
            "already-tool-created-adrs-exist check above silently answer 'no' when the true answer is 'yes'."
        ),
        "arguments": [
            {"name": "path", "alias": "-p", "type": "string", "required": True, "description": "Repository root directory."},
        ],
        "failure_codes": build_failure_codes(
            {
                FailureCodes.TARGET_DIRECTORY_NOT_FOUND: "--path does not point to an existing directory.",
                FailureCodes.CONFIG_NOT_FOUND: "--path's own directory has no adr-config.adrplus.",
                FailureCodes.FOLDERADR_CHANGED_AFTER_LOCK_ACQUIRED: "A concurrent config change moved folderadr while this call was acquiring the repository lock -- no file is touched either way; retry.",
                FailureCodes.MIGRATION_PATTERN_NOT_CONFIGURED: "Both the repository's own migrationpattern and the install-level config's own fallback are empty.",
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER: "A candidate's own title (sourced from its raw legacy filename) contains '|', a line-break-like character, a filesystem-unsafe character, or consists entirely of whitespace/'_'/'-' -- a per-file failure, not a whole-batch abort.",
                FailureCodes.MIGRATION_SCAN_FAILED: "A candidate's own header could not even be read (permission denied or similar) -- refuses the whole run.",
                FailureCodes.MIGRATION_SCAN_INCOMPLETE: "A subdirectory under the decisions folder could not be scanned -- refuses the whole run.",
                FailureCodes.MIGRATION_SCAN_UNRELIABLE_ENCODING: "A scanned candidate's content isn't valid UTF-8 -- refuses the whole run.",
                FailureCodes.ALREADY_TOOL_CREATED_ADRS_EXIST: "At least one scanned file already has a valid, non-migrated header -- refuses the whole run.",
                FailureCodes.NO_DECISIONS_FOUND: "No .md files matching a recognized naming scheme were found.",
                FailureCodes.NO_ELIGIBLE_FILES_TO_MIGRATE: "Every recognized file already has a header (migrated or tool-created) -- nothing needs migration.",
                FailureCodes.MIGRATION_LOCK_LOST: "The repository lock was lost partway through -- data.results names only the candidates actually attempted before the loss.",
                FailureCodes.MIGRATION_WRITE_FAILED: "At least one candidate failed to write -- data.results names every candidate's own outcome.",
                FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
                FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
                FailureCodes.IO_ERROR: "A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
            },
            CONFIG_FAILURE_CODES,
            LOCK_FAILURE_CODES,
        ),
    }


def run(args):
    path = parse_flags(args, required=("path",), aliases={"p": "path"})["path"]
    target, config_path, config = resolve_target_and_config(path)

    folder = resolve_within(target, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # Without this lock, migrate could silently erase a concurrent
        # approve's already-committed write, even when approve correctly
        # held the lock and its own verify_still_held() passed honestly --
        # a missing lock here defeats ADR001's guarantee for a command
        # that did everything right, not just for migrate itself racing
        # against a second migrate. The whole scan-decide-write flow is
        # one critical section, same as every other mutating command.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Re-reads fresh in case folderadr changed between the
            # pre-lock read and lock acquisition -- operating against a
            # stale folder would be silently wrong.
            config = verify_folderadr_unchanged_since_lock(config_path, config.folderadr, warnings=warnings)

            # ADR002V01: the fallback decision and its persist-back write
            # both happen HERE, on the fresh post-lock config, never on
            # the pre-lock read above -- ADR001's freshness principle,
            # same as every other write this command (and every other
            # mutating command) already follows. A concurrent direct
            # `config --migrationpattern` edit racing this call is always
            # seen fresh: if it lands first, this read already has a
            # non-empty value and no fallback is even considered.
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
                # Persists the found value back into the repo's own
                # config, matching the reference tool's own behavior -- covered
                # by the same lock as the rest of this critical section,
                # not a separate write outside it.
                merged = asdict(config)
                merged["migrationpattern"] = fallback_pattern
                merged_text = json.dumps(merged, indent=2, ensure_ascii=False)
                config = parse_repo_config(merged_text)  # re-validates the merged result; raises on failure
                lock.verify_still_held()
                attempts = atomic_write_text(config_path, merged_text)
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(warning)

            entries = []  # (ParsedFileName, Path, HeaderParseResult)
            unreliable_files = []
            if folder.is_dir():
                # Resolved once, not once per candidate -- see is_within's
                # own note.
                try:
                    resolved_folder = folder.resolve()
                except (OSError, ValueError):
                    resolved_folder = None
                excluded = []
                for candidate in folder.rglob("*.md"):
                    if not is_within(folder, candidate, resolved_base=resolved_folder):
                        excluded.append(candidate)
                        continue
                    found = parse_any_filename(candidate.name, config)
                    if found is None:
                        continue
                    _, parsed = found
                    try:
                        # A lossy decode (errors="replace") with no signal
                        # would let a single invalid UTF-8 byte in an
                        # otherwise-valid, already-tool-created header's
                        # status-label cell make parse_header see it as
                        # invalid, bypassing the already-tool-created-adrs-
                        # exist safety check below and letting the file get
                        # a SECOND header stamped onto it. Same lossy-decode
                        # detection every other read in this project already
                        # uses; entries with a lossy read are set aside below,
                        # never trusted for a safety-critical decision.
                        #
                        # Reads only the bounded header (parse_header never
                        # looks past it, and the write loop below copies
                        # body bytes through raw, untouched either way), not
                        # the whole candidate.
                        lines, encoding_repaired = read_header_lines_with_report(candidate)
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
                    if encoding_repaired:
                        unreliable_files.append(str(candidate))
                    # Deliberately does not surface header.marker_label_
                    # mismatches (ADR004V01) here -- this scan is a bulk
                    # eligibility pass over every candidate, not a report
                    # on one specific target file the way read_target's
                    # own warning already covers.
                    entries.append((parsed, candidate, parse_header(lines, config)))

                # Same as scan_decisions/explore -- an is_within-excluded
                # candidate is reported, not dropped with zero signal.
                warning = excluded_candidate_warning(excluded)
                if warning:
                    warnings.append(warning)
                # rglob above silently swallows an OSError from an
                # unreadable subdirectory -- see
                # find_unreadable_subdirectories' own note. Fails closed
                # instead of warning -- unlike explore's own best-effort
                # listing, this scan feeds already-tool-created-adrs-exist
                # below, a real safety decision (a hidden already-migrated
                # file could make that check silently answer "no" when the
                # true answer is "yes"). Same fail-closed treatment this
                # command already gives an unreadable FILE
                # (migration-scan-failed) -- a directory it can't enter is
                # the identical risk, just one level up.
                unreadable_dirs = find_unreadable_subdirectories(folder)
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

            if unreliable_files:
                # A lossy decode can't be trusted for either the safety check
                # right below (it could be hiding a genuine, already-migrated
                # header) or candidate eligibility (it could wrongly qualify a
                # file that was never meant to be touched) -- refuse the whole
                # run rather than guess, since migrate is a one-time, largely
                # irreversible bulk operation.
                raise CommandError(
                    FailureCodes.MIGRATION_SCAN_UNRELIABLE_ENCODING,
                    f"{len(unreliable_files)} file(s) could not be decoded cleanly as UTF-8; migration refuses "
                    "to run until they're fixed (their true header state can't be trusted).",
                    data={"unreliable_files": unreliable_files},
                    warnings=warnings,
                )

            if any(header.is_valid and not header.is_migrated for _, _, header in entries):
                raise CommandError(
                    FailureCodes.ALREADY_TOOL_CREATED_ADRS_EXIST,
                    "This repository already has decisions created by this tool; migration refuses to run.",
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
            # Deliberate hardening beyond the reference tool, whose own
            # per-file loop has no try/catch either -- an exception there
            # propagates and loses even the partial `result` list it had
            # already built, so this isn't a fidelity requirement to
            # preserve.
            results = []
            for parsed, candidate_path in candidates:
                try:
                    # ADR001, part 3: guarantees this write never commits
                    # blindly if the lease was reclaimed. Checked before
                    # every candidate's write, not just once, since this
                    # loop can run for a while.
                    lock.verify_still_held()
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
                    # untouched; only the header text is new). Retries a
                    # transient PermissionError on EITHER the source read
                    # or the destination write via one shared retry budget
                    # (atomic_write_chunks' own loop calls the chunk
                    # generator, which does the source read, from inside
                    # the same try/except as the destination write) --
                    # deliberately combined, not two independent budgets;
                    # see ADR006V01's own "Negative Consequences".
                    attempts = atomic_write_chunks(
                        candidate_path,
                        lambda: _stream_migrated_candidate(candidate_path, header_text, lock),
                    )
                    warning = retry_warning(attempts)
                    if warning:
                        warnings.append(warning)
                    results.append({"file": str(candidate_path), "status": "migrated", "error": None})
                except LockLostError:
                    # Distinct from the per-file OSError/UnicodeError case
                    # just below -- losing the lock is a whole-operation
                    # event, not this one candidate's own problem, so
                    # looping on would just re-lose the same already-gone
                    # lock on every remaining candidate and misreport each
                    # of them as individually "failed" when none were ever
                    # attempted. Stop outright and report exactly what was
                    # actually done so far.
                    raise CommandError(
                        FailureCodes.MIGRATION_LOCK_LOST,
                        f"The repository lock was lost after {len(results)} of {len(candidates)} file(s) were "
                        "processed; migration was aborted rather than continuing unprotected.",
                        data={"results": results},
                        warnings=warnings,
                    )
                except (OSError, UnicodeError, CommandError) as error:
                    # UnicodeError (e.g. a UnicodeEncodeError from a title
                    # containing a lone surrogate) is not an OSError, but is
                    # just as plausible here as a real per-file failure --
                    # catching only OSError would let it escape the whole
                    # loop, discarding every result already collected.
                    # CommandError is the title-validation check just above
                    # (a hostile legacy filename) -- same per-file treatment,
                    # not a whole-batch abort; LockLostError, itself a
                    # CommandError subclass, is already caught by the more
                    # specific clause above and never reaches this one.
                    results.append({"file": str(candidate_path), "status": "failed", "error": str(error)})

            failed = [entry for entry in results if entry["status"] == "failed"]
            if failed:
                raise CommandError(
                    FailureCodes.MIGRATION_WRITE_FAILED,
                    f"{len(failed)} of {len(results)} file(s) failed to migrate.",
                    data={"results": results},
                    warnings=warnings,
                )

            migrated = [entry["file"] for entry in results]

    return {"migrated": migrated, "warnings": warnings}
