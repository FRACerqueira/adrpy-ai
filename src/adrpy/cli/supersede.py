"""`supersede` command: marks an Accepted decision as Superseded and
creates its successor. The successor never copies the predecessor's body (always starts from the
config's default template) and its filename suffix is unconditional,
never a collision-disambiguator. `--open` is permanently not implemented
(see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.errors import CommandError, FailureCodes, build_failure_codes
from adrpy.core.header import SHARED_FAILURE_CODES as HEADER_FAILURE_CODES, DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text, cleanup_orphaned_temp_files
from adrpy.core.lifecycle import (
    SHARED_FAILURE_CODES as LIFECYCLE_FAILURE_CODES,
    family_members,
    has_pending_sibling,
    has_superseded_sibling,
    ineligibility_reason_for_supersede,
    mark_superseded,
    next_number,
    parse_refdate,
    read_target,
    resolve_repo_and_target,
    scan_decisions,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import SHARED_FAILURE_CODES as LOCK_FAILURE_CODES, LockLostError, acquire_repo_lock
from adrpy.core.naming import build_filename
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    FailureCodes.STILL_PROPOSED: "This decision must be Accepted before it can be superseded; it is still Proposed.",
    FailureCodes.ALREADY_REJECTED: "This decision was Rejected, not Accepted; only Accepted decisions can be superseded.",
    FailureCodes.ALREADY_SUPERSEDED: "This decision has already been superseded.",
    FailureCodes.NOT_PROPOSED: "This decision's own status is not Proposed.",
    FailureCodes.UNEXPECTED_STATUS: "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "supersede",
        "summary": "Marks an Accepted decision Superseded and creates its successor.",
        "description": (
            "Marks an Accepted decision as Superseded and creates its successor. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "Refuses with family-member-superseded if another member of the same family has "
            "already been superseded, or family-member-pending if another member is still "
            "unresolved (Proposed) -- no write is made either way. "
            "This is two writes in sequence, not one: a failure creating the successor "
            "(supersede-successor-write-failed) means success=false even though the predecessor "
            "was already committed to Superseded -- that code's own `data.predecessor`/"
            "`data.predecessor_status` names the file already mutated despite the overall failure "
            "(a lock lost before this SECOND write also surfaces this same code/data, not lock-lost). "
            "May instead fail with repository-locked (lock never acquired) or lock-lost (lost before the "
            "FIRST write) -- in both of those cases no write was made at all. May also fail with "
            "folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while "
            "this call was acquiring the lock -- no write was made either way; retry. May also fail with "
            "family-scan-incomplete or supersede-successor-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "and successor-number allocation can't be trusted from an incomplete scan; no write was made "
            "either way. May also fail with family-scan-unreliable-encoding (data.unreliable_files names "
            "the affected file(s)) if a sibling needed a lossy UTF-8 decode -- its parsed header can't be "
            "trusted for a safety decision either, the same reasoning as an unreadable subdirectory; no "
            "write was made. The successor's own title -- the predecessor's own filename segment, "
            "re-validated before use, unless --title overrides it (see its own argument description) -- "
            "may fail with field-contains-forbidden-character if it carries '|', a line-break-like "
            "character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control character; the successor's "
            "title lands inside an actual filename component, not just a header-table cell), or consists "
            "entirely of "
            "whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a "
            "value raw, which can collide with the filename's own separator and produce a successor the "
            "tool can never recognize again; no write is made. Fails with one of still-proposed, "
            "already-rejected, already-superseded, not-proposed, or unexpected-status (the target's own "
            "current status makes Superseded unreachable from here) if the target isn't eligible -- no "
            "write is made. Fails with file-already-exists (data.file names it) if the successor's own "
            "resulting filename already exists on disk -- no write is made either. If the PREDECESSOR's "
            "own write (marking it Superseded, the FIRST of the two writes) fails with an OSError, that "
            "surfaces as supersede-write-failed instead of a generic io-error, for discoverability -- "
            "nothing was written in that case."
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
                    "Domain for the successor; defaults to the predecessor's own value. Cannot contain '|' "
                    "or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    "Scope for the successor; defaults to the predecessor's own value. Cannot contain '|' "
                    "or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "refdate",
                "alias": "-r",
                "type": "string",
                "required": False,
                "description": (
                    "Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before "
                    "the predecessor's own last update date (or creation date, if never updated) "
                    "(refdate-invalid-format/refdate-in-future/refdate-before-history)."
                ),
            },
            {
                "name": "title",
                "alias": "-t",
                "type": "string",
                "required": False,
                "description": (
                    "Title for the successor; defaults to the predecessor's own filename-segment title "
                    "(unlike --scope/--domain, this default is NOT re-editable via the header's prose title "
                    "-- see the description above). Cannot contain '|' or a line-break-like character, or a "
                    "filesystem-unsafe character (`<>:\"/\\|?*` or a control character -- title lands inside "
                    "an actual filename component, not just a header-table cell); also cannot consist "
                    "entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls "
                    "back to echoing such a value raw, which can collide with the filename's own separator "
                    "and produce a successor the tool can never recognize again "
                    "(field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
        ],
        "failure_codes": build_failure_codes(
            _INELIGIBILITY_DETAILS,
            {
                FailureCodes.FAMILY_MEMBER_PENDING: "Another member of the same family is still unresolved (Proposed).",
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not a strict ISO date (YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before the predecessor's own last update date (or creation date, if never updated).",
                FailureCodes.FIELD_IS_BLANK: "--scope or --domain is a raw, non-empty flag value that is blank after stripping whitespace.",
                FailureCodes.FILE_ALREADY_EXISTS: "The successor's own resulting filename already exists on disk.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The successor's own title, once case-transformed, would produce a filename this tool could never recognize again.",
                FailureCodes.SUPERSEDE_SUCCESSOR_SCAN_INCOMPLETE: "A subdirectory under the decisions folder could not be scanned while allocating the successor's own number.",
                FailureCodes.SUPERSEDE_WRITE_FAILED: "The predecessor's own write (marking it Superseded, the FIRST of the two writes) failed -- nothing was written.",
                FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED: "The successor's own write (the SECOND of the two writes) failed -- the predecessor was already committed to Superseded.",
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
        optional=("domain", "scope", "refdate", "title"),
        aliases={"f": "file", "d": "domain", "s": "scope", "r": "refdate", "t": "title"},
    )
    config, root, path = resolve_repo_and_target(flags["file"])
    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # Covers the same next-number race as `new` (two concurrent calls
        # could otherwise compute the same sequence number), plus
        # mark_superseded's mutation of the predecessor, so a concurrent
        # scan by another command never observes it half-transitioned.
        #
        # The predecessor's own header/lines are read fresh, inside the
        # lock, instead of before it -- without this, two concurrent
        # supersede calls on the SAME predecessor could each write it from
        # their own stale, pre-lock snapshot, producing two live successors
        # with only one referenced by the predecessor at all.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Re-reads fresh in case folderadr changed between the pre-lock
            # read and lock acquisition -- operating against a stale folder
            # would be silently wrong.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, encoding_repaired = read_target(path, config, warnings=warnings)

            # A specific reason code, not one collapsed not-eligible-for-
            # supersede, so the caller knows which recovery action applies.
            reason = ineligibility_reason_for_supersede(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

            # Without this, two different members of the same family could
            # each be independently superseded, producing two live
            # successors. Same guard version.py/revise.py already use.
            members = family_members(
                folder, config, filename_info.number, warnings=warnings, exclude_from_encoding_check=path
            )
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
            not_before = header.date_update or header.date_create
            if not_before is not None:
                validate_refdate_not_before(refdate, not_before)

            # Unlike `new`, an omitted --scope/--domain defaults to the
            # predecessor's own current value, not empty.
            scope = flags["scope"] if "scope" in flags else (header.scope or "")
            domain = flags["domain"] if "domain" in flags else (header.domain or "")
            reject_embedded_delimiter(scope, "scope")
            reject_embedded_delimiter(domain, "domain")
            if "title" in flags:
                # An explicit --title overrides the predecessor's own
                # filename-segment title -- validated exactly like `new
                # --title` (same 3 checks, same order).
                title = flags["title"]
                reject_embedded_delimiter(title, "title")
                reject_filesystem_unsafe_title(title, "title")
                reject_title_with_no_case_transform_content(title, "title")
            else:
                # `title` is re-read from the PREDECESSOR's own filename
                # segment, not a live flag -- a hand-edited or migrated file
                # could already carry a filesystem-unsafe character (e.g. ':',
                # an NTFS Alternate-Data-Stream separator), which build_filename
                # below would otherwise propagate into a real write attempt.
                reject_embedded_delimiter(filename_info.title, "title")
                reject_filesystem_unsafe_title(filename_info.title, "title")
                reject_title_with_no_case_transform_content(filename_info.title, "title")
                title = filename_info.title

            # strict=True: an unreadable subdirectory hiding a
            # higher-numbered decision must never be silently treated as
            # "not found" here, or the allocated successor number could
            # collide once that subdirectory becomes readable again.
            successor_number = next_number(
                scan_decisions(
                    folder, config, warnings=warnings, strict=True,
                    incomplete_code=FailureCodes.SUPERSEDE_SUCCESSOR_SCAN_INCOMPLETE,
                )
            )

            successor = DecisionRecord(
                number=successor_number,
                # Defaults to the predecessor's own FILENAME segment
                # (already case-transformed), not its header's prose title --
                # confirmed via live comparison against the reference tool.
                # Overridden by --title when given (see above).
                title=title,
                version=1,
                revision=1 if config.lenrevision > 0 else None,
                scope=scope,
                domain=domain,
                status_create="Proposed",
                date_create=refdate,
                superseded=filename_info.number,
            )
            filename = build_filename(config, successor)
            successor_path = resolve_within(folder, filename)
            if successor_path.exists():
                raise CommandError(
                    FailureCodes.FILE_ALREADY_EXISTS,
                    f"File already exists: {filename}",
                    data={"file": filename},
                    warnings=warnings,
                )

            try:
                # ADR001, part 3: guarantees the predecessor write below
                # never commits blindly if the lease was reclaimed.
                lock.verify_still_held()
                _record, body_encoding_repaired, attempts = mark_superseded(
                    path, config, header, filename_info, successor_number, refdate, lock=lock
                )
                # Accurate only because the write above already succeeded.
                # ADR006V01: combines the header's own flag (known since
                # read_target) with the body's own (only known now, from
                # the streamed write).
                if encoding_repaired or body_encoding_repaired:
                    warnings.append(encoding_repaired_warning(path))
            except OSError as error:
                # Nothing has been written yet at this point (the
                # predecessor's own mutation IS this write) -- the
                # generic attach_warnings safety net's io-error is
                # already the right shape, just give it a command-
                # specific code for discoverability.
                raise CommandError(
                    FailureCodes.SUPERSEDE_WRITE_FAILED, f"{path}: {error}", warnings=warnings
                ) from error
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

            content = build_header(config, successor) + config.template
            try:
                # ADR001, part 3: this command's SECOND write -- guarantees
                # it never commits blindly either, on its own.
                lock.verify_still_held()
                attempts = atomic_write_text(successor_path, content)
            except (OSError, LockLostError) as error:
                # By this point the predecessor has ALREADY been marked
                # Superseded for real (the write above already succeeded)
                # -- data names that partial mutation explicitly, so a
                # caller doesn't have to infer an orphaned family state
                # from a generic io-error. Both OSError and LockLostError
                # are caught here (not just OSError), so a lock lost on
                # this second write reports the same orphaned-family risk
                # instead of a generic, dataless "no write was made".
                raise CommandError(
                    FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED,
                    f"{successor_path}: {error}",
                    data={
                        "predecessor": str(path),
                        "predecessor_status": "Superseded",
                        "intended_successor": str(successor_path),
                    },
                    warnings=warnings,
                ) from error
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"predecessor": str(path), "created": str(successor_path), "status": "Proposed", "warnings": warnings}
