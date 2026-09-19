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

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_bytes, atomic_write_text, cleanup_orphaned_temp_files
from adrpy.core.config import parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header, parse_header
from adrpy.core.install_config import read_install_config_text
from adrpy.core.io_retry import read_with_permission_retry
from adrpy.core.lifecycle import read_header_lines_with_report, resolve_target_and_config, verify_folderadr_unchanged_since_lock
from adrpy.core.lock import LockLostError, acquire_repo_lock
from adrpy.core.naming import parse_any_filename
from adrpy.core.security import find_unreadable_subdirectories, is_within, resolve_within
from adrpy.core.warnings import attach_warnings, excluded_candidate_warning, orphan_cleanup_warning, retry_warning


def describe():
    return {
        "name": "migrate",
        "description": (
            "Adds an AdrPlus-compliant header to existing, hand-written decision files. "
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
                        "migration-pattern-not-configured",
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
                            "migration-scan-failed",
                            f"{candidate}: {error}",
                            data={"unreadable_file": str(candidate)},
                            warnings=warnings,
                        ) from error
                    if encoding_repaired:
                        unreliable_files.append(str(candidate))
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
                        "migration-scan-incomplete",
                        f"Cannot safely scan for existing decisions: {len(unreadable_dirs)} subdirectory/"
                        "subdirectories could not be scanned (permission denied or similar).",
                        data={"folder": str(folder), "unreadable": unreadable_dirs},
                        warnings=warnings,
                    )

            if not entries:
                raise CommandError(
                    "no-decisions-found",
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
                    "migration-scan-unreliable-encoding",
                    f"{len(unreliable_files)} file(s) could not be decoded cleanly as UTF-8; migration refuses "
                    "to run until they're fixed (their true header state can't be trusted).",
                    data={"unreliable_files": unreliable_files},
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
                    # Raw bytes, not text: the original content's own line
                    # endings (and anything else about its bytes) must pass
                    # through completely untouched -- only the header text is
                    # new. The one exception, confirmed live: the reference tool
                    # discards a leading UTF-8 BOM when reading, so it never
                    # appears in the migrated result -- pass it through here
                    # and it lands stranded in the middle of the file, after
                    # the new header.
                    #
                    # Retries a transient PermissionError the same way this
                    # command's own SCAN-phase read of this exact file
                    # already does (read_header_lines_with_report, a few
                    # dozen lines above) -- without this, a transient blip
                    # here would permanently misclassify the candidate as
                    # "failed" in a one-time, largely irreversible operation,
                    # instead of retrying like its sibling read of the same
                    # file already would.
                    raw_bytes = read_with_permission_retry(candidate_path.read_bytes)
                    if raw_bytes.startswith(b"\xef\xbb\xbf"):
                        raw_bytes = raw_bytes[3:]
                    record = DecisionRecord(number=parsed.number, title=(parsed.title or "").strip(), version=0)
                    header_text = build_header(config, record, migrated=True)
                    attempts = atomic_write_bytes(candidate_path, header_text.encode("utf-8") + raw_bytes)
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
                        "migration-lock-lost",
                        f"The repository lock was lost after {len(results)} of {len(candidates)} file(s) were "
                        "processed; migration was aborted rather than continuing unprotected.",
                        data={"results": results},
                        warnings=warnings,
                    )
                except (OSError, UnicodeError) as error:
                    # UnicodeError (e.g. a UnicodeEncodeError from a title
                    # containing a lone surrogate) is not an OSError, but is
                    # just as plausible here as a real per-file failure --
                    # catching only OSError would let it escape the whole
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
