"""`revise` command: creates a new revision (minor change) of an
Accepted/Rejected decision. Unlike `version`, revise has no --scope/
--domain and no --empty -- it always carries the source's content
forward, and its scope/domain come from the TARGET file's own header,
not the latest member's. --open is permanently not implemented (see
`new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import SHARED_FAILURE_CODES as HEADER_FAILURE_CODES, DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_chunks, cleanup_orphaned_temp_files
from adrpy.core.lifecycle import (
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
    FailureCodes.STILL_PROPOSED: "This decision must be Accepted or Rejected before a new revision can be created.",
    FailureCodes.ALREADY_SUPERSEDED: "This decision has already been superseded.",
    FailureCodes.NOT_PROPOSED: "This decision's own status is not Proposed.",
    FailureCodes.UNEXPECTED_STATUS: "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "revise",
        "summary": "Creates a new revision (wording fix) of an Accepted/Rejected decision.",
        "description": (
            "Creates a new revision (wording fix) of an Accepted/Rejected decision. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "Requires the repository's lenrevision to be > 0 (see the `config` command); "
            "fails with revision-not-configured otherwise -- true for any freshly-init'd repository. "
            "May fail with repository-locked if the repository lock could not be acquired in time, or "
            "lock-lost if it was acquired but reclaimed by another process before the write could commit -- "
            "in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write was "
            "made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "can't be trusted from an incomplete scan; no write was made. May also fail with "
            "family-scan-unreliable-encoding (data.unreliable_files names the affected file(s)) if a sibling "
            "needed a lossy UTF-8 decode -- its parsed header can't be trusted for a safety decision either, "
            "the same reasoning as an unreadable subdirectory; no write was made. The target's own title/scope/"
            "domain (all re-read from its header cells, not flags -- this command has none for scope/"
            "domain) are re-validated before use -- may fail with field-contains-forbidden-character if a "
            "hand-edited or migrated source file carries '|', a line-break-like character in any of the "
            "three, a filesystem-unsafe character in title specifically (`<>:\"/\\|?*` or a control "
            "character; title lands inside an actual filename component, not just a header-table cell), or "
            "title consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step "
            "falls back to echoing such a value raw, which can collide with the filename's own separator "
            "and produce a file the tool can never recognize again. Fails with family-not-found if this "
            "decision's own family can't be resolved, or lenrevision-too-small-for-new-revision "
            "(data.new_revision/data.lenrevision) if the next revision number doesn't fit the configured "
            "width -- no write is made either way. If this isn't the latest version/revision in its "
            "family (and isn't the one documented branch-off-a-rejected-latest exception), fails with "
            "not-latest-version (data names the actual latest member). Fails with one of still-proposed, "
            "already-superseded, not-proposed, or unexpected-status if the target isn't eligible, or "
            "family-member-superseded/family-member-pending if another member of the same family has "
            "already been superseded or is still unresolved (Proposed). Fails with file-already-exists "
            "(data.file names it) if the resulting filename already exists on disk. No write is made in "
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
        ],
        "failure_codes": build_failure_codes(
            _INELIGIBILITY_DETAILS,
            {
                FailureCodes.FAMILY_MEMBER_PENDING: "Another member of the same family is still unresolved (Proposed).",
                FailureCodes.FAMILY_NOT_FOUND: "This decision's own family could not be resolved.",
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not a strict ISO date (YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before the LATEST family member's own last update date (or creation date, if never updated).",
                FailureCodes.FILE_ALREADY_EXISTS: "The new revision's own resulting filename already exists on disk.",
                FailureCodes.LENREVISION_TOO_SMALL_FOR_NEW_REVISION: "The next revision number does not fit in the configured lenrevision width.",
                FailureCodes.NOT_LATEST_VERSION: "This decision is not the latest version/revision in its family (and isn't the one documented branch-off-a-rejected-latest exception).",
                FailureCodes.REVISION_NOT_CONFIGURED: "This repository's config has lenrevision == 0.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The new revision's own title, once case-transformed, would produce a filename this tool could never recognize again.",
            },
            LIFECYCLE_FAILURE_CODES,
            HEADER_FAILURE_CODES,
            CONFIG_FAILURE_CODES,
            LOCK_FAILURE_CODES,
        ),
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("refdate",), aliases={"f": "file", "r": "refdate"})
    config, root, path = resolve_repo_and_target(flags["file"])

    if config.lenrevision == 0:
        raise CommandError(
            FailureCodes.REVISION_NOT_CONFIGURED, "This repository's config has lenrevision == 0."
        )

    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # Same reasoning as `version`'s own comment -- the family-state read
        # and write must be one critical section, and the target's own
        # header is read fresh, inside the lock, instead of via
        # load_target before it.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Re-reads fresh in case folderadr changed between the pre-lock
            # read and lock acquisition -- operating against a stale folder
            # would be silently wrong.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, encoding_repaired = read_target(path, config, warnings=warnings)
            # revise never rewrites its own source either -- see version.py's
            # own comment: ADR006V01 defers this warning until after the
            # write below, since the body is no longer read until then.

            # One scan shared by all three checks below, avoiding a
            # duplicate scan_decisions call each.
            members = family_members(
                folder, config, filename_info.number, warnings=warnings, exclude_from_encoding_check=path
            )
            latest = latest_in_family(folder, config, filename_info.number, members=members)
            if latest is None:
                raise CommandError(
                    FailureCodes.FAMILY_NOT_FOUND, "Could not resolve this decision's own family.", warnings=warnings
                )
            latest_parsed, latest_header, latest_path = latest

            if len(str((latest_parsed.revision or 0) + 1)) > config.lenrevision:
                raise CommandError(
                    FailureCodes.LENREVISION_TOO_SMALL_FOR_NEW_REVISION,
                    f"New revision {(latest_parsed.revision or 0) + 1} does not fit in lenrevision={config.lenrevision}.",
                    data={"new_revision": (latest_parsed.revision or 0) + 1, "lenrevision": config.lenrevision},
                    warnings=warnings,
                )

            if latest_path.resolve() != path.resolve():
                # Same branch-off-a-rejected-latest exception as `version`, but
                # revision-only (revise never bumps the version number).
                allowed = latest_header.status_update == "Rejected" and (latest_parsed.revision or 0) > (
                    filename_info.revision or 0
                )
                if not allowed:
                    # Names the actual latest member as structured data --
                    # see `version`'s own comment.
                    raise CommandError(
                        FailureCodes.NOT_LATEST_VERSION,
                        "This decision is not the latest version/revision in its family.",
                        data={
                            "latest_file": str(latest_path),
                            "latest_version": latest_parsed.version,
                            "latest_revision": latest_parsed.revision,
                            "latest_status": latest_header.status_update,
                        },
                        warnings=warnings,
                    )

            # A specific reason code, not one collapsed not-eligible-for-
            # revision, so the caller knows which recovery action applies.
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

            # title/scope/domain are all re-read from the SOURCE file's own
            # header cells, not live flags -- unlike `version`, which
            # re-validates scope/domain even when they fall back to the
            # latest member's own value, this command never did, so a
            # hand-edited or migrated file's control character (e.g. VT,
            # confirmed live to survive an unrelated revise unchanged) would
            # otherwise propagate silently into every future revision's own
            # header, plus title's own filesystem-unsafe risk (e.g. ':', an
            # NTFS Alternate-Data-Stream separator) at build_filename below.
            reject_embedded_delimiter(header.title, "title")
            reject_filesystem_unsafe_title(header.title, "title")
            reject_title_with_no_case_transform_content(header.title, "title")
            reject_embedded_delimiter(header.scope, "scope")
            reject_embedded_delimiter(header.domain, "domain")

            record = DecisionRecord(
                number=filename_info.number,
                title=header.title,
                version=header.version or 0,
                revision=(header.revision or 0) + 1,
                scope=header.scope,
                domain=header.domain,
                status_create="Proposed",
                date_create=refdate,
            )

            filename = build_filename(config, record)
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
            # ADR006V01: streams the source's own body straight from
            # `path` into the new file, without ever holding it in memory.
            header_text = build_header(config, record)
            body_report = {}

            def _chunks(path=path, header_text=header_text, body_report=body_report, lock=lock):
                yield header_text.encode("utf-8")
                yield from stream_normalized_body_chunks(path, body_report)
                # Re-verify right before this generator exhausts -- see
                # core/lifecycle.py's _rewrite_with_streamed_body for why
                # (the pre-call check above alone no longer closes the
                # check-to-commit gap once the write is a real stream, not
                # an in-memory write).
                lock.verify_still_held()

            attempts = atomic_write_chunks(new_path, _chunks)
            if encoding_repaired or body_report["encoding_repaired"]:
                warnings.append(encoding_repaired_source_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"created": str(new_path), "status": "Proposed", "warnings": warnings}
