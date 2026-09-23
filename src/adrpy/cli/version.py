"""`version` command: creates a new major version of an Accepted/Rejected
decision. `--open` is permanently not implemented (see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import SHARED_FAILURE_CODES as HEADER_FAILURE_CODES, DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_chunks, atomic_write_text, cleanup_orphaned_temp_files
from adrpy.core.lifecycle import (
    raise_if_not_latest,
    raise_if_rejected_successor,
    SHARED_FAILURE_CODES as LIFECYCLE_FAILURE_CODES,
    family_members,
    has_pending_sibling,
    has_superseded_sibling,
    ineligibility_reason_for_version_or_revise,
    latest_in_family,
    parse_refdate,
    read_target,
    resolve_repo_and_target,
    stream_normalized_body_chunks,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import SHARED_FAILURE_CODES as LOCK_FAILURE_CODES, acquire_repo_lock
from adrpy.core.naming import build_filename
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, encoding_repaired_source_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    FailureCodes.STILL_PROPOSED: "This decision must be Accepted or Rejected before a new version can be created.",
    FailureCodes.ALREADY_SUPERSEDED: "This decision has already been superseded.",
    FailureCodes.NOT_PROPOSED: "This decision's own status is not Proposed.",
    FailureCodes.UNEXPECTED_STATUS: "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "version",
        "summary": "Creates a new major version of an Accepted/Rejected decision.",
        "description": (
            "Creates a new major version of an Accepted/Rejected decision. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "May fail with repository-locked if the repository lock could not be acquired in time, or "
            "lock-lost if it was acquired but reclaimed by another process before the write could commit -- "
            "in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write was "
            "made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "can't be trusted from an incomplete scan; no write was made. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). "
            "The target's own title (re-read "
            "from its header cell, not a flag) is re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character; title lands inside an actual filename component, not just a header-table cell), or "
            "consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls "
            "back to echoing such a value raw, which can collide with the filename's own separator and "
            "produce a successor file the tool can never recognize again. Fails with family-not-found if "
            "this decision's own family can't be resolved, or lenversion-too-small-for-new-version "
            "(data.new_version/data.lenversion) if the next version number doesn't fit the configured "
            "width -- no write is made either way. Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless the newer ones are a single Rejected member (see doc/lifecycle.md). Fails with rejected-successor-is-final if the "
            "target belongs to the family of a successor that was rejected. Fails with one of still-proposed, "
            "already-superseded, not-proposed, or unexpected-status if the target isn't eligible, or "
            "family-member-superseded/family-member-pending if another member of the same family has "
            "already been superseded or is still unresolved (Proposed). Fails with file-already-exists "
            "(data.file names it) if the resulting filename already exists on disk, or if any file of "
            "this family already holds the number it would create -- whatever its title, whether or not "
            "its header parses. No write is made in "
            "any of these cases."
        ),
        "arguments": [
            {
                "name": "file",
                "alias": "-f",
                "type": "string",
                "required": True,
                "description": "Path to the decision file. A bare name with no extension gets '.md' appended.",
            },
            {
                "name": "domain",
                "alias": "-d",
                "type": "string",
                "required": False,
                "description": (
                    "Domain for the new version; defaults to the latest version's own value. Cannot contain "
                    "'|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    "Scope for the new version; defaults to the latest version's own value. Cannot contain "
                    "'|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "refdate",
                "alias": "-r",
                "type": "string",
                "required": False,
                "description": (
                    "Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before "
                    "the LATEST family member's own last update date (or creation date, if never updated) "
                    "-- not necessarily this file's own date, when branching off an older Rejected sibling "
                    "(refdate-invalid-format/refdate-in-future/refdate-before-history)."
                ),
            },
            {
                "name": "empty",
                "alias": "-e",
                "type": "switch",
                "required": False,
                # Presence-only (`--empty` with no value, like a getopt
                # flag), not "boolean" -- `--empty true`/`--empty false`
                # both fail with "Unknown argument", unlike
                # `config --disableplugins`, which does take a value.
                "description": (
                    "Start from the default template instead of carrying the source's content forward. "
                    "Presence-only: pass just '--empty' with no value; do not pass '--empty true/false'."
                ),
            },
        ],
        "failure_codes": build_failure_codes(
            _INELIGIBILITY_DETAILS,
            {
                FailureCodes.FAMILY_MEMBER_PENDING: "Another member of the same family is still unresolved (Proposed).",
                FailureCodes.FAMILY_NOT_FOUND: "This decision's own family could not be resolved.",
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before the LATEST family member's own last update date (or creation date, if never updated).",
                FailureCodes.FIELD_IS_BLANK: "--scope or --domain is a raw, non-empty flag value that is blank after stripping whitespace.",
                FailureCodes.FILE_ALREADY_EXISTS: "The new version's number is already held by a file of this family (any title, header valid or not), or its resulting filename already exists -- data.file names it.",
                FailureCodes.LENVERSION_TOO_SMALL_FOR_NEW_VERSION: "The next version number does not fit in the configured lenversion width.",
                FailureCodes.NOT_LATEST_VERSION: "A newer member of this family locks this one -- only the latest member can change, unless the newer ones are a single Rejected member (data names the newer file).",
                FailureCodes.REJECTED_SUCCESSOR_IS_FINAL: "This decision belongs to the family of a successor that was rejected -- the end of its line; supersede its predecessor again instead.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The new version's own title, once case-transformed, would produce a filename this tool could never recognize again.",
            },
            LIFECYCLE_FAILURE_CODES,
            HEADER_FAILURE_CODES,
            CONFIG_FAILURE_CODES,
            LOCK_FAILURE_CODES,
        ),
    }


def run(args):
    flags = parse_flags(
        args,
        required=("file",),
        optional=("domain", "scope", "refdate"),
        switches=("empty",),
        aliases={"f": "file", "d": "domain", "s": "scope", "r": "refdate", "e": "empty"},
    )
    config, root, path = resolve_repo_and_target(flags["file"])
    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # The family-state read (latest/sibling checks) and the eventual
        # write must be one critical section -- a concurrent
        # supersede/approve/etc. on a sibling could otherwise slip in
        # between, and this call's next-version-number decision could go
        # stale before it's ever written. Same class as `new`'s own comment.
        # The target's own header is read fresh, inside the lock, instead
        # of via load_target before it -- same freshness fix as
        # approve/reject/undo/supersede.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Re-reads fresh in case folderadr changed between the pre-lock
            # read and lock acquisition -- operating against a stale folder
            # would be silently wrong.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, encoding_repaired = read_target(path, config, warnings=warnings)
            # version never rewrites its own source (only its BODY is
            # carried into a newly created file) -- encoding_repaired_
            # source_warning's "the file has been rewritten" claim is never
            # true here. ADR006V01: the body is no longer read at all
            # unless/until the write below actually streams it, so this
            # warning (which is specifically about the BODY's own decode,
            # not just the header's) can only be finalized once that
            # streamed write has happened -- combined with `encoding_
            # repaired` (the header's own flag, already known here) right
            # after the write, not right away.

            # One scan shared by all three checks below, avoiding a
            # duplicate scan_decisions call each.
            ignored = []
            members = family_members(
                folder, config, filename_info.number, warnings=warnings, ignored=ignored
            )
            latest = latest_in_family(folder, config, filename_info.number, members=members)
            if latest is None:
                raise CommandError(
                    FailureCodes.FAMILY_NOT_FOUND, "Could not resolve this decision's own family.", warnings=warnings
                )
            latest_parsed, latest_header, latest_path = latest
            new_version = latest_parsed.version + 1

            if len(str(new_version)) > config.lenversion:
                raise CommandError(
                    FailureCodes.LENVERSION_TOO_SMALL_FOR_NEW_VERSION,
                    f"New version {new_version} does not fit in lenversion={config.lenversion}.",
                    data={"new_version": new_version, "lenversion": config.lenversion},
                    warnings=warnings,
                )

            raise_if_not_latest(filename_info, members, warnings)
            raise_if_rejected_successor(members, warnings)

            # A specific reason code, not one collapsed not-eligible-for-
            # version, so the caller knows which recovery action applies.
            reason = ineligibility_reason_for_version_or_revise(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)
            if has_superseded_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    FailureCodes.FAMILY_MEMBER_SUPERSEDED,
                    "A sibling decision in this family has already been superseded.",
                    warnings=warnings,
                )
            if has_pending_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    FailureCodes.FAMILY_MEMBER_PENDING,
                    "Another decision in this family is still unresolved (Proposed).",
                    warnings=warnings,
                )

            refdate = parse_refdate(flags.get("refdate"))
            validate_refdate_not_in_future(refdate)
            not_before = latest_header.date_update or latest_header.date_create
            if not_before is not None:
                validate_refdate_not_before(refdate, not_before)

            # Unlike `new`, an omitted --scope/--domain defaults to the LATEST
            # family member's own current value, not empty -- and not the
            # branch-target's value either, when branching off an older Rejected
            # sibling.
            scope = flags["scope"] if "scope" in flags else (latest_header.scope or "")
            domain = flags["domain"] if "domain" in flags else (latest_header.domain or "")
            reject_embedded_delimiter(scope, "scope")
            reject_embedded_delimiter(domain, "domain")
            # `title` is re-read from the SOURCE file's own header cell, not a
            # live flag -- a hand-edited or migrated file could already carry
            # a filesystem-unsafe character (e.g. ':', an NTFS Alternate-Data-
            # Stream separator), which build_filename below would otherwise
            # propagate into a real write attempt.
            reject_embedded_delimiter(header.title, "title")
            reject_filesystem_unsafe_title(header.title, "title")
            reject_title_with_no_case_transform_content(header.title, "title")

            record = DecisionRecord(
                number=filename_info.number,
                title=header.title,
                version=new_version,
                revision=1 if config.lenrevision > 0 else None,
                scope=scope,
                domain=domain,
                status_create="Proposed",
                date_create=refdate,
            )

            filename = build_filename(config, record)
            # The filename decides numbering, counting every file: a version
            # number already held by any file of this family is taken, never
            # given to a second file.
            taken = next((entry[2] for entry in members + ignored if entry[0].version == new_version), None)
            if taken is not None:
                raise CommandError(
                    FailureCodes.FILE_ALREADY_EXISTS,
                    f"Version {new_version} is already held by {taken.name}.",
                    data={"file": taken.name},
                    warnings=warnings,
                )
            new_path = resolve_within(folder, filename)
            if new_path.exists():
                raise CommandError(
                    FailureCodes.FILE_ALREADY_EXISTS,
                    f"File already exists: {filename}",
                    data={"file": filename},
                    warnings=warnings,
                )

            # ADR001, part 3: guarantees this write never commits blindly
            # if the lease was reclaimed.
            lock.verify_still_held()
            # ADR006V01: --empty uses config.template (schema-bounded, safe
            # in memory, unchanged); otherwise the SOURCE's own body is
            # streamed straight from `path` into the new file, without
            # ever holding it in memory. body_encoding_repaired stays
            # False (the default a fresh report dict would carry) when
            # --empty means the body is never read at all.
            header_text = build_header(config, record)
            if flags.get("empty"):
                attempts = atomic_write_text(new_path, header_text + config.template)
                body_encoding_repaired = False
            else:
                body_report = {}

                def _chunks(path=path, header_text=header_text, body_report=body_report, lock=lock):
                    yield header_text.encode("utf-8")
                    yield from stream_normalized_body_chunks(path, body_report)
                    # Re-verify right before this generator exhausts (i.e.
                    # right before atomic_write_chunks's own commit) -- the
                    # pre-call check above only proves the lock was held
                    # before this now-potentially-slow streamed read/write
                    # began. See core/lifecycle.py's
                    # _rewrite_with_streamed_body for the same reasoning and
                    # the live-confirmed regression this closes.
                    lock.verify_still_held()

                attempts = atomic_write_chunks(new_path, _chunks)
                body_encoding_repaired = body_report["encoding_repaired"]
            if encoding_repaired or body_encoding_repaired:
                warnings.append(encoding_repaired_source_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"created": str(new_path), "status": "Proposed", "warnings": warnings}
