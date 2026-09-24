"""`reject` command: marks a Proposed decision as Rejected. When the
rejected decision was itself a successor
(its filename carries a supersede suffix), the predecessor's Superseded
status is undone too -- the attempted supersession failed along with the
successor.

The predecessor is reverted FIRST, before this decision's own status is
written (round-36 retraction of the original order: writing this
decision's own status first left a real, permanently unrecoverable stuck
state if the predecessor's own revert then failed -- status_change is
treated as a terminal state by every one of this project's lifecycle
commands, with no "unsupersede" verb, so a predecessor stuck Superseded
could never be touched again). With the predecessor reverted first, every
failure up to and including that write leaves nothing committed at all,
safely retryable from scratch.
"""

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
from adrpy.core.lock import SHARED_FAILURE_CODES as LOCK_FAILURE_CODES, LockLostError, acquire_repo_lock
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
    FailureCodes.NOT_PROPOSED: "This decision's own Created status is not Proposed -- no command writes that; repair its Created cell by hand.",
    FailureCodes.UNEXPECTED_STATUS: "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell); undo clears the Changed cell.",
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
            "(created by `supersede`), the predecessor's Superseded status is reverted FIRST, before "
            "this decision's own status is written -- the result's `undone_predecessor` names that file "
            "when this happens, or is null otherwise. This is two writes in sequence, not one, but in "
            "this order every failure up to and including the predecessor's own write leaves NOTHING "
            "committed at all: superseded-predecessor-not-found or reject-predecessor-write-failed (a "
            "real OSError on that write; a lock lost there surfaces the standard lock-lost instead, also "
            "with nothing committed), or -- if the scan for the predecessor's own family hits an "
            "unreadable subdirectory -- family-scan-incomplete, all mean no write was made and the "
            "call is safely retryable from scratch. Only reject-own-write-failed-after-predecessor-"
            "reverted is a genuine partial success: the predecessor was already reverted for real when "
            "writing THIS decision's own Rejected status then failed -- `data.predecessor_file` names "
            "the file already reverted. Retrying `reject` on the same file after that specific failure "
            "is safe and completes the operation: when no member of the predecessor's family is "
            "Superseded any more (the revert already happened, or the predecessor was never marked at "
            "all -- an interrupted supersede), there is nothing to revert and "
            "reject proceeds straight to this decision's own write (`undone_predecessor` null). It "
            "fails with superseded-predecessor-not-found instead when some member of that family IS "
            "Superseded but not pointing at this decision (another successor took over, or a "
            "back-reference edited by hand) -- reject only ever reverts a Superseded mark that names "
            "this decision -- or when any file named into that family (by its number) has a header that "
            "does not parse, damaged or missing, so its status can't be read (`data.unparseable_files` "
            "names it; repair or remove it by hand and retry). That refusal applies to the retry above "
            "too. May instead fail with repository-locked "
            "(lock never acquired) or lock-lost (lost before any write) -- in both of those cases no "
            "write was made at all. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write "
            "was made either way; retry. May also fail with family-scan-incomplete BEFORE any write (this "
            "decision's own family scan, unrelated to the predecessor lookup above) if a subdirectory under "
            "the decisions folder could not be scanned -- no write made in that case. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). "
            "The target's own title/scope/domain "
            "(re-read from its header cells, not flags) are re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character), or consists entirely of whitespace/'_'/'-'; no write made in that case either. "
            "BEFORE any write, fails with one "
            "of already-accepted, already-rejected, already-superseded, not-proposed, or unexpected-status "
            "(the target's own current status makes Rejected unreachable from here) if the target isn't "
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
                FailureCodes.SUPERSEDED_PREDECESSOR_NOT_FOUND: "This decision's own predecessor (per its filename's supersede suffix) could not be found, a member of its family is Superseded but not pointing at this decision, or -- when no valid member names this decision -- a file of that family does not parse (data.unparseable_files); no write was made.",
                FailureCodes.REJECT_PREDECESSOR_WRITE_FAILED: "Reverting the predecessor's Superseded status failed with a real OSError -- no write was made.",
                FailureCodes.REJECT_OWN_WRITE_FAILED_AFTER_PREDECESSOR_REVERTED: "The predecessor's Superseded status was already reverted for real, but writing this decision's own Rejected status then failed -- data.predecessor_file names the file already reverted; retry is safe.",
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

            # Round-36 retraction of the original order (this decision's own
            # write, then the predecessor's): reverting the predecessor
            # FIRST means every failure up to and including that write
            # leaves nothing committed at all -- always safely retryable
            # from scratch, instead of risking a predecessor stuck
            # Superseded forever with no command able to touch it again
            # (status_change is a terminal state everywhere else in this
            # codebase; there is no "unsupersede" verb).
            undone_predecessor = None
            if filename_info.superseded_from is not None:
                # No write has happened yet at this point, so a scan
                # failure here needs no special partial-success re-raise --
                # it propagates exactly like this command's own primary
                # family scan above.
                pred_ignored = []
                pred_members = family_members(
                    folder, config, filename_info.superseded_from, warnings=warnings, ignored=pred_ignored
                )
                pred_unparseable = [str(entry[2]) for entry in pred_ignored]
                # latest_in_family picks whichever sibling has the highest
                # (version, revision) -- not necessarily the one this
                # successor actually came from. Reachable whenever the
                # predecessor's family has more than one member (e.g. an
                # earlier `version` bump) and the superseded member isn't
                # the latest. Match the specific member this successor's
                # own number was stamped onto instead (mark_superseded's own
                # superseded_by_file, a bare zero-padded sequence number,
                # never a filename). Compared as a number: the padding is the
                # lenseq in force when it was written, which a later config
                # change may have altered.
                def names_this_successor(ref):
                    ref = (ref or "").strip()
                    return ref.isascii() and ref.isdigit() and int(ref) == filename_info.number

                predecessor = next(
                    (
                        member
                        for member in pred_members
                        if member[1].status_change == "Superseded" and names_this_successor(member[1].superseded_by_file)
                    ),
                    None,
                )
                if predecessor is None:
                    # Two distinct reasons this can happen: a genuinely
                    # missing/corrupted predecessor reference (must fail
                    # loudly), or this exact successor was already
                    # processed once by an earlier call whose OWN write
                    # (below) then failed -- the predecessor revert already
                    # succeeded and cleared status_change, and with it the
                    # superseded_by_file back-reference this match depends
                    # on, so there is no live link left to re-derive from.
                    # Recognize the second case -- or a successor whose
                    # predecessor was never marked at all (an interrupted
                    # supersede) -- only when it is
                    # unambiguous: no member of the predecessor's family is
                    # Superseded at all, so there is nothing to revert in any
                    # reading. When some member IS Superseded (pointing at
                    # another successor, or with a back-reference edited by
                    # hand), that case still fails loudly: reject only reverts a Superseded
                    # mark that names this successor. Residual, accepted risk: a
                    # corrupted predecessor-sequence reference in the
                    # successor's own filename that happens to name a real,
                    # never-superseded family would also match here and be
                    # silently accepted -- narrow (requires a corrupted
                    # filename AND a coincidental real match) and disclosed,
                    # since nothing in that family's own content can tell
                    # "already reverted" from "never superseded" either way.
                    # A member whose header doesn't parse is left out of
                    # pred_members, and its status can't be read -- it may
                    # be the Superseded one, so it refuses, naming the file.
                    if pred_unparseable:
                        raise CommandError(
                            FailureCodes.SUPERSEDED_PREDECESSOR_NOT_FOUND,
                            f"Could not tell whether the decision this one superseded (sequence "
                            f"{filename_info.superseded_from}) is still marked Superseded: "
                            f"{', '.join(pred_unparseable)} has a header that does not parse. Repair it by "
                            "hand and retry. No write was made.",
                            data={"unparseable_files": pred_unparseable},
                            warnings=warnings,
                        )
                    already_reverted = bool(pred_members) and all(
                        member[1].status_change is None for member in pred_members
                    )
                    if not already_reverted:
                        raise CommandError(
                            FailureCodes.SUPERSEDED_PREDECESSOR_NOT_FOUND,
                            f"Could not find the decision this one superseded (sequence "
                            f"{filename_info.superseded_from}). No write was made.",
                            warnings=warnings,
                        )
                else:
                    pred_parsed, pred_header, pred_path = predecessor
                    # pred_header already comes from pred_members' own scan
                    # (family_members, via read_header_lines_with_report) --
                    # no separate read needed for the header portion. It
                    # parsed, so whatever that read replaced did not affect
                    # the status read from it -- only the BODY's own encoding
                    # status (ADR006V01, known only once the streamed write
                    # below has read it) can still need the warning.
                    # ADR001, part 3: guarantees this write (and this
                    # decision's own, below) never commits blindly if the
                    # lease was reclaimed.
                    lock.verify_still_held()
                    try:
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
                    except OSError as error:
                        # Nothing committed -- atomic_write_chunks leaves
                        # the predecessor file untouched on failure, the
                        # same guarantee every other writer in this project
                        # has. A LockLostError here is deliberately NOT
                        # caught -- it already carries its own standard,
                        # widely-documented lock-lost code, which already
                        # means "no write was made"; wrapping it in a
                        # reject-specific code would add nothing since
                        # there is no partial-success data to attach yet.
                        raise CommandError(
                            FailureCodes.REJECT_PREDECESSOR_WRITE_FAILED,
                            f"{pred_path}: {error}. No write was made.",
                            warnings=warnings,
                        ) from error
                    if pred_body_encoding_repaired:
                        warnings.append(encoding_repaired_warning(pred_path))
                    warning = retry_warning(attempts)
                    if warning:
                        warnings.append(warning)
                    undone_predecessor = str(pred_path)

            # This decision's own write, last. If the predecessor above was
            # already reverted for real and THIS write now fails, that
            # partial success is real and reported explicitly -- a caller
            # doesn't have to infer it from `warnings` alone or discover it
            # only by re-reading the predecessor file itself. Retrying
            # `reject` on this same file is then safe: the predecessor
            # lookup above finds no member Superseded any more and skips
            # straight to this write again.
            try:
                # Inside the try: a lock lost here, after the predecessor
                # revert above already committed, is that same partial
                # success -- not a bare lock-lost ("no write was made").
                lock.verify_still_held()
                _record, body_encoding_repaired, attempts = rewrite_status_field(
                    path, config, header, filename_info, field="update", status="Rejected", refdate=refdate, lock=lock
                )
            except (OSError, LockLostError) as error:
                if undone_predecessor is not None:
                    raise CommandError(
                        FailureCodes.REJECT_OWN_WRITE_FAILED_AFTER_PREDECESSOR_REVERTED,
                        f"{path}: {error}. The predecessor ({undone_predecessor}) was already reverted for real; run reject on "
                        "this decision again to finish.",
                        data={"predecessor_file": undone_predecessor},
                        warnings=warnings,
                    ) from error
                raise
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

    # Canonical keyword, not the repo's configured status label.
    return {"file": str(path), "status": "Rejected", "undone_predecessor": undone_predecessor, "warnings": warnings}
