"""`reject` command: marks a Proposed decision as Rejected. When the
rejected decision was itself a successor
(its filename carries a supersede suffix), the predecessor's Superseded
status is undone too -- the attempted supersession failed along with the
successor.
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.lifecycle import (
    family_members,
    has_superseded_sibling,
    ineligibility_reason_for_approve_or_reject,
    parse_refdate,
    read_target,
    resolve_repo_and_target,
    rewrite_status_field,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import LockLostError, acquire_repo_lock
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    FailureCodes.ALREADY_ACCEPTED: "This decision is already Accepted; run undo first to reconsider it.",
    FailureCodes.ALREADY_REJECTED: "This decision is already Rejected.",
    FailureCodes.ALREADY_SUPERSEDED: "This decision has already been superseded.",
    FailureCodes.NOT_PROPOSED: "This decision's own status is not Proposed.",
    FailureCodes.UNEXPECTED_STATUS: "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "reject",
        "summary": "Marks a Proposed decision Rejected.",
        "description": (
            "Marks a Proposed decision as Rejected. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "If this decision is itself a successor "
            "(created by `supersede`), also reverts the predecessor's Superseded status -- the "
            "result's `undone_predecessor` names that file when this happens, or is null otherwise. "
            "This is two writes in sequence, not one: a failure reverting the predecessor "
            "(superseded-predecessor-not-found, reject-predecessor-write-failed, or -- if the scan for the "
            "predecessor's own family hits an unreadable subdirectory or a sibling needing a lossy UTF-8 "
            "decode -- family-scan-incomplete/family-scan-unreliable-encoding) means "
            "success=false even though this decision's OWN status was already committed to Rejected -- "
            "each of those four codes' own `data.file`/`data.status` names the file already mutated "
            "despite the overall failure (a lock lost before this SECOND write also surfaces "
            "reject-predecessor-write-failed, not lock-lost). May instead fail with repository-locked "
            "(lock never acquired) or lock-lost (lost before the FIRST write) -- in both of those cases no "
            "write was made at all. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write "
            "was made either way; retry. May also fail with family-scan-incomplete or "
            "family-scan-unreliable-encoding BEFORE the first write (this decision's own family scan, "
            "unrelated to the predecessor lookup above) if a subdirectory under the decisions folder could "
            "not be scanned, or a sibling needed a lossy UTF-8 decode whose parsed header can't be trusted "
            "for a safety decision -- no write made in that case. The target's own title/scope/domain "
            "(re-read from its header cells, not flags) are re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character), or consists entirely of whitespace/'_'/'-'; no write made in that case either. "
            "BEFORE the first write, fails with one "
            "of already-accepted, already-rejected, already-superseded, not-proposed, or unexpected-status "
            "(the target's own current status makes Rejected unreachable from here) if the target isn't "
            "eligible, or family-member-superseded if another member of the same family has already been "
            "superseded -- no write is made in any of these cases."
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

        # ADR001's coverage requirement (doc/adr/ADR001V01-...): the read
        # below happens fresh, inside the lock, never from a pre-lock read.
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
            # rejection, so the caller knows which recovery action applies.
            reason = ineligibility_reason_for_approve_or_reject(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

            # Pre-fetching members here is also how the scan's own warnings
            # (an excluded is_within candidate) reach this command.
            members = family_members(
                folder, config, filename_info.number, warnings=warnings, exclude_from_encoding_check=path
            )
            if has_superseded_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    FailureCodes.FAMILY_MEMBER_SUPERSEDED,
                    "A sibling decision in this family has already been superseded.",
                    warnings=warnings,
                )

            refdate = parse_refdate(flags.get("refdate"))
            validate_refdate_not_in_future(refdate)
            if header.date_create is not None:
                validate_refdate_not_before(refdate, header.date_create)

            # Round 28: title/scope/domain are re-read from the SOURCE
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

            # ADR001, part 3: guarantees this write (and the predecessor's,
            # below) never commit blindly if the lease was reclaimed.
            lock.verify_still_held()
            _record, body_encoding_repaired, attempts = rewrite_status_field(
                path, config, header, filename_info, field="update", status="Rejected", refdate=refdate, lock=lock
            )
            # Accurate only because the write above already succeeded --
            # the warning claims the file was rewritten. ADR006V01:
            # combines the header's own flag (known since read_target)
            # with the body's own (only known now, from the streamed
            # write).
            if encoding_repaired or body_encoding_repaired:
                warnings.append(encoding_repaired_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

            undone_predecessor = None
            if filename_info.superseded_from is not None:
                try:
                    pred_members = family_members(
                        folder, config, filename_info.superseded_from, warnings=warnings
                    )
                except CommandError as error:
                    # This scan runs AFTER the primary write above already
                    # committed -- unlike every other family_members call in
                    # this codebase, all of which run before their command's
                    # own first write. Neither of family_members' own two
                    # scan-safety codes (family-scan-incomplete,
                    # family-scan-unreliable-encoding) carries `data.file`/
                    # `data.status`, unlike this command's other two
                    # second-phase codes -- re-raise with that same
                    # partial-success shape, merging in the original error's
                    # own `data` (`folder`/`unreadable`, or
                    # `unreliable_files`) rather than discarding it, so this
                    # second-phase failure keeps both diagnostic payloads,
                    # not just this command's own.
                    raise CommandError(
                        error.code,
                        str(error),
                        data={**(error.data or {}), "file": str(path), "status": "Rejected"},
                        warnings=warnings,
                    ) from error
                # latest_in_family picks whichever sibling has the highest
                # (version, revision) -- not necessarily the one this
                # successor actually came from. Reachable whenever the
                # predecessor's family has more than one member (e.g. an
                # earlier `version` bump) and the superseded member isn't
                # the latest. Match the specific member this successor's
                # own number was stamped onto instead (mark_superseded's own
                # superseded_by_file, a bare zero-padded sequence number,
                # never a filename).
                successor_ref = f"{filename_info.number:0{config.lenseq}d}"
                predecessor = next(
                    (
                        member
                        for member in pred_members
                        if member[1].status_change == "Superseded" and member[1].superseded_by_file == successor_ref
                    ),
                    None,
                )
                if predecessor is None:
                    # By this point the primary write above has already
                    # succeeded for real -- `path` genuinely is Rejected on
                    # disk. `data` names that partial success explicitly, so
                    # a caller doesn't have to infer it from `warnings`
                    # alone (there may be none) or discover it only by
                    # re-reading the file itself.
                    raise CommandError(
                        FailureCodes.SUPERSEDED_PREDECESSOR_NOT_FOUND,
                        f"Could not find the decision this one superseded (sequence {filename_info.superseded_from}).",
                        data={"file": str(path), "status": "Rejected"},
                        warnings=warnings,
                    )
                pred_parsed, pred_header, pred_path = predecessor
                # pred_header already comes from pred_members' own scan
                # (family_members, via read_header_lines_with_report) --
                # no separate read needed for the header portion. That
                # same scan's own fail-closed check (family-scan-
                # unreliable-encoding) already guarantees this exact
                # header wasn't lossy-decoded, or this call would never
                # have reached here -- only the BODY's own encoding
                # status (ADR006V01, known only once the streamed write
                # below has read it) can still need the warning.
                try:
                    # ADR001, part 3: this is this command's SECOND write --
                    # guarantees it never commits blindly either, on its own,
                    # even though the first write above already succeeded.
                    lock.verify_still_held()
                    _record, pred_body_encoding_repaired, attempts = rewrite_status_field(
                        pred_path,
                        config,
                        pred_header,
                        pred_parsed,
                        field="change",
                        status=None,
                        refdate=None,
                        lock=lock,
                    )
                    # Accurate only because this second write already
                    # succeeded.
                    if pred_body_encoding_repaired:
                        warnings.append(encoding_repaired_warning(pred_path))
                except (OSError, LockLostError) as error:
                    # By this point the primary write above has already
                    # succeeded for real -- `path` genuinely is Rejected on
                    # disk. Same partial-success shape as this command's own
                    # superseded-predecessor-not-found case, just for a real
                    # OSError or a LockLostError (both caught here, not just
                    # OSError, so a lock lost on this second write also
                    # reports that partial success instead of a generic,
                    # dataless lock-lost).
                    raise CommandError(
                        FailureCodes.REJECT_PREDECESSOR_WRITE_FAILED,
                        f"{pred_path}: {error}",
                        data={"file": str(path), "status": "Rejected", "predecessor_file": str(pred_path)},
                        warnings=warnings,
                    ) from error
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(warning)
                undone_predecessor = str(pred_path)

    # Canonical keyword, not the repo's configured status label.
    return {"file": str(path), "status": "Rejected", "undone_predecessor": undone_predecessor, "warnings": warnings}
