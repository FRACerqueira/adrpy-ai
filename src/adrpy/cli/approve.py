"""`approve` command: marks a Proposed decision as Accepted."""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import SHARED_FAILURE_CODES as HEADER_FAILURE_CODES
from adrpy.core.lifecycle import (
    raise_if_superseded_sibling,
    raise_if_not_latest,
    SHARED_FAILURE_CODES as LIFECYCLE_FAILURE_CODES,
    family_members,
    ineligibility_reason_for_approve_or_reject,
    parse_refdate,
    read_target,
    resolve_repo_and_target,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import SHARED_FAILURE_CODES as LOCK_FAILURE_CODES, acquire_repo_lock
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    FailureCodes.ALREADY_ACCEPTED: "This decision is already Accepted.",
    FailureCodes.ALREADY_REJECTED: "This decision is already Rejected; run undo first to reconsider it (unless it belongs to a rejected successor's family, whose line is final -- supersede its predecessor again).",
    FailureCodes.ALREADY_SUPERSEDED: "This decision has already been superseded.",
    FailureCodes.NOT_PROPOSED: "This decision's own Created status is not Proposed -- no command writes that; repair its Created cell by hand.",
    FailureCodes.UNEXPECTED_STATUS: "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell); undo clears the Changed cell.",
}


def describe():
    return {
        "name": "approve",
        "summary": "Marks a Proposed decision Accepted.",
        "description": (
            "Marks a Proposed decision as Accepted. "
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
            "The target's own title/scope/"
            "domain (re-read from its header cells, not flags) are re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character), or consists entirely of whitespace/'_'/'-' -- this command never renames the file "
            "itself, but rewrites its header with the same fields a later rename-capable command "
            "(version/revise/supersede) would also need to trust. Fails with one of "
            "already-accepted, already-rejected, already-superseded, not-proposed, or unexpected-status "
            "(the target's own current status makes Accepted unreachable from here) if the target isn't "
            "eligible, or family-member-superseded if another member of the same family has already been "
            "superseded -- no write is made in any of these cases. Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). "
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
                    "this decision's own creation date (refdate-invalid-format/refdate-in-future/"
                    "refdate-before-history)."
                ),
            },
        ],
        "failure_codes": build_failure_codes(
            _INELIGIBILITY_DETAILS,
            {
                FailureCodes.NOT_LATEST_VERSION: "A newer member of this family locks this one -- only the latest member can change, unless every newer one is Rejected (data.latest_file names the newer file).",
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before this decision's own creation date.",
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
    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # ADR001's coverage requirement (doc/adr/ADR001V01-...): without this
        # lock, concurrent approve/reject calls on the same file each
        # read-decide-write independently, both reporting success with
        # mutually exclusive final statuses. The read below happens fresh,
        # inside the lock, instead of before it.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # `folder` above was resolved from a config read BEFORE this
            # lock -- a concurrent config change could have moved folderadr
            # in the window before the lock was actually acquired, in which
            # case this lock no longer names the repository's real decisions
            # folder. Re-reads fresh and aborts rather than operating
            # against a directory nobody uses anymore.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, encoding_repaired = read_target(path, config, warnings=warnings)

            # A specific reason code, not one collapsed not-eligible-for-
            # approval -- already-accepted/already-rejected/already-
            # superseded each call for a different recovery action.
            reason = ineligibility_reason_for_approve_or_reject(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

            # Pre-fetching members here is also how the scan's own warnings
            # (an excluded is_within candidate) reach this command.
            members = family_members(
                folder, config, filename_info.number, warnings=warnings
            )
            raise_if_superseded_sibling(members, warnings)
            raise_if_not_latest(filename_info, members, warnings)

            refdate = parse_refdate(flags.get("refdate"))
            validate_refdate_not_in_future(refdate)
            if header.date_create is not None:
                validate_refdate_not_before(refdate, header.date_create)

            # title/scope/domain are re-read from the SOURCE
            # file's own header cells, not flags -- a hand-edited or
            # migrated file could carry a filesystem-unsafe character
            # (e.g. ':', an NTFS Alternate-Data-Stream separator) never
            # validated until this rewrite. Same defensive re-validation
            # version/revise/supersede/migrate already apply.
            reject_embedded_delimiter(header.title, "title")
            reject_filesystem_unsafe_title(header.title, "title")
            reject_title_with_no_case_transform_content(header.title, "title")
            reject_embedded_delimiter(header.scope, "scope")
            reject_embedded_delimiter(header.domain, "domain")

            # ADR001, part 3: the lease can still be reclaimed out from
            # under a legitimately slow holder -- this can't prevent that,
            # but guarantees the write below never commits blindly if it
            # already happened.
            lock.verify_still_held()
            _record, body_encoding_repaired, attempts = rewrite_status_field(
                path, config, header, filename_info, field="update", status="Accepted", refdate=refdate, lock=lock
            )
            # encoding_repaired_warning claims "the file has been rewritten
            # ... bytes are now lost" -- only true once the write above has
            # actually happened, not at read time (an eligibility check
            # could still have failed first). ADR006V01: combines the
            # header's own flag (known since read_target, above) with the
            # body's own (only known now, once the streamed write has
            # actually read it) -- either half being lossy loses bytes on
            # this rewrite.
            if encoding_repaired or body_encoding_repaired:
                warnings.append(encoding_repaired_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, matching explore's own status_create/status_update
    # -- not the repo's configured status label.
    return {"file": str(path), "status": "Accepted", "warnings": warnings}
