"""`supersede` command: marks an Accepted decision as Superseded and
creates its successor. The successor never copies the predecessor's body (always starts from the
config's default template) and its filename suffix is unconditional,
never a collision-disambiguator. `--open` is permanently not implemented
(see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.errors import CommandError, FailureCodes, UsageError, build_failure_codes
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


def _not_resumable_reason(orphans, predecessor_header):
    """Why --resume can't resume here, naming the step that fixes it."""
    if not orphans:
        return ("--resume found no existing successor of this decision to resume onto; run supersede "
                "without --resume to create one.")
    names = ", ".join(orphan[0].name for orphan in orphans)
    if len(orphans) > 1:
        return (f"--resume needs exactly one existing successor of this decision, but {len(orphans)} point "
                f"at it ({names}); reject all but one, then run --resume again.")
    name, orphan = orphans[0][0].name, orphans[0][2]
    if orphan.status_change is not None:
        return (f"{name} was itself superseded since; reject its own successor first (which reverts it -- "
                "undo that successor first if it was approved, and repeat down the chain if it was itself "
                "superseded), then undo it if it had been approved, then run "
                "--resume again.")
    if orphan.status_update is not None:
        return f"{name} is no longer Proposed ({orphan.status_update}); undo it back to Proposed, then run --resume again."
    if orphan.is_migrated and not predecessor_header.is_migrated:
        return (f"{name} is a migrated placeholder (no status of its own), but this decision is not migrated "
                "(it was created, versioned or revised by this tool); a placeholder is only adopted onto a "
                "migrated predecessor. Reject it to create a new successor instead.")
    return (f"{name} has no Created status and date of its own, so it cannot be resumed onto, and no command "
            "can act on it: repair its Created cell by hand and run --resume again, or delete it and run "
            "supersede without --resume.")


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
            "This is two writes in sequence, not one, successor first: a failure creating the "
            "successor (supersede-successor-write-failed) means nothing was written. A failure "
            "marking the predecessor Superseded afterward (supersede-write-failed) means success=false "
            "even though the successor already exists -- that code's own `data.successor` names it, "
            "and `data.predecessor_status` is still Accepted (a lock lost before this SECOND write also "
            "surfaces this same code/data, not lock-lost). The successor keeps its number on disk, so "
            "no later `new` can take it; re-run with --resume to finish: it finds that successor "
            "(the existing file whose supersede suffix points back at this decision), marks only the "
            "predecessor, and says so in `warnings`. Without --resume, any existing non-Rejected "
            "successor pointing back at this decision -- left by that failure, or by rejecting and then "
            "undoing an earlier successor, which looks identical on disk -- is refused with "
            "supersede-successor-already-exists (data.file/data.files name it) instead of being guessed "
            "at: reject it to create a new successor, or --resume to use it (one approved since must be "
            "undone back to Proposed first -- neither reject nor --resume accepts an Accepted successor; one "
            "itself superseded since needs its own successor rejected first, which reverts it -- that successor "
            "undone first if it was approved, repeating down the chain if it was itself superseded -- then "
            "undo if it had been approved). Only a file with a later sequence number than this decision counts as its "
            "successor; one pointing back from the same number (itself or its own family) or a lower one is "
            "ignored. "
            "A Rejected successor is the "
            "normal end of an earlier attempt and never counts. --resume itself fails with "
            "supersede-orphaned-successor-not-resumable (data.files names what was found) unless exactly "
            "one such successor exists and it is still Proposed with its own Created status and date -- or "
            "both it and this decision are migrated placeholders with no status yet (a chain recorded in the "
            "filenames before adrpy, adopted as is; `status` is then null) -- and "
            "with refdate-before-history if --refdate is before that successor's creation; no write is "
            "made in any of these cases. Rejecting a still-Proposed successor directly works too: with no "
            "member of this decision's family marked Superseded, reject has nothing to revert. May instead fail with repository-locked (lock never acquired) or lock-lost (lost before "
            "the FIRST write) -- in both of those cases no write was made at all. May also fail with "
            "folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while "
            "this call was acquiring the lock -- no write was made either way; retry. May also fail with "
            "family-scan-incomplete or supersede-successor-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "and successor-number allocation can't be trusted from an incomplete scan; no write was made "
            "either way. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). A file pointing back at this decision whose header does not parse "
            "is not guessed at: supersede refuses and names it in data.file. "
            "The successor's own title -- the predecessor's own filename segment, "
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
            "resulting filename already exists on disk -- no write is made either."
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
            {
                "name": "resume",
                "type": "switch",
                "required": False,
                "description": (
                    "Finish an earlier supersede of this decision onto the successor it already created, "
                    "marking only the predecessor -- see the description above for exactly when that is "
                    "allowed. Cannot be combined with --title, --scope or --domain (usage-error): the "
                    "existing successor is kept as it was created. Presence-only."
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
                FailureCodes.SUPERSEDE_WRITE_FAILED: "The predecessor's own write (marking it Superseded, the SECOND of the two writes) failed -- the successor already exists (data.successor); re-run supersede with --resume to finish.",
                FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED: "The successor's own write (the FIRST of the two writes) failed -- nothing was written (data.intended_successor names the file that would have been created).",
                FailureCodes.SUPERSEDE_ORPHANED_SUCCESSOR_NOT_RESUMABLE: "--resume was given, but there is not exactly one non-Rejected successor of this decision still Proposed with its own Created status and date, or a migrated placeholder successor of a migrated placeholder (data.files names what was found) -- no write was made.",
                FailureCodes.SUPERSEDE_SUCCESSOR_ALREADY_EXISTS: "A non-Rejected successor already points back at this decision (data.file/data.files name it) and --resume was not given -- no write was made; reject it to create a new successor, or re-run with --resume.",
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
        switches=("resume",),
        aliases={"f": "file", "d": "domain", "s": "scope", "r": "refdate", "t": "title"},
    )
    resume = flags.get("resume", False)
    if resume and any(name in flags for name in ("title", "scope", "domain")):
        # A resumed successor keeps the content it was created with; these
        # would otherwise be accepted and silently ignored.
        raise UsageError("--resume cannot be combined with --title, --scope or --domain: the existing "
                         "successor is kept exactly as it was created.")
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
                folder, config, filename_info.number, warnings=warnings
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
            # collide once that subdirectory becomes readable again -- and,
            # for the orphan check below, a hidden successor would be
            # missed and a second one created.
            decisions = scan_decisions(
                folder, config, warnings=warnings, strict=True,
                incomplete_code=FailureCodes.SUPERSEDE_SUCCESSOR_SCAN_INCOMPLETE,
            )

            # The successor is written FIRST (below), so an earlier call
            # whose predecessor write then failed leaves a file already
            # pointing back at this still-Accepted predecessor. So can a
            # normal sequence with no failure at all (supersede, reject the
            # successor, undo that reject), and nothing on disk tells the
            # two apart -- so this never guesses: an existing non-Rejected
            # successor is only resumed onto when the caller asks for it
            # with --resume, and refused otherwise. A Rejected one is the
            # normal end of an earlier attempt (reject reverts the
            # predecessor to Accepted) and never counts.
            orphans = []
            for scheme_entry in decisions:
                if getattr(scheme_entry[1], "superseded_from", None) != filename_info.number:
                    continue
                # A successor always gets a later sequence number than its
                # predecessor (next_number): a file pointing back from the
                # same number (itself, or a member of its own family) or a
                # lower one is not a successor of this decision at all --
                # adopting one would supersede a decision by itself or by an
                # older one, with no command able to undo it.
                if scheme_entry[1].number <= filename_info.number:
                    continue
                try:
                    candidate_info, candidate_header, _repaired = read_target(scheme_entry[2], config, warnings=warnings)
                except CommandError as error:
                    # Otherwise this reads as if --file itself were bad.
                    if error.data is None:
                        error.data = {"file": str(scheme_entry[2])}
                    raise
                if candidate_header.status_update != "Rejected":
                    orphans.append((scheme_entry[2], candidate_info, candidate_header))
            orphan_files = [str(orphan[0]) for orphan in orphans]
            if orphans and not resume:
                raise CommandError(
                    FailureCodes.SUPERSEDE_SUCCESSOR_ALREADY_EXISTS,
                    f"{len(orphans)} existing successor(s) already point at this decision "
                    f"({', '.join(orphan[0].name for orphan in orphans)}). Re-run with --resume to finish "
                    "superseding onto it, or reject it to create a new successor. First, if it was itself "
                    "superseded since, reject its own successor (which reverts it -- undo that successor first "
                    "if it was approved, and repeat down the chain if it was itself superseded); then, if it "
                    "had been approved, undo it.",
                    data={"file": orphan_files[0], "files": orphan_files},
                    warnings=warnings,
                )
            if resume:
                # A migrated placeholder has no Created status of its own;
                # it is adopted only when the predecessor is a migrated
                # placeholder too -- a supersede chain recorded by hand, in
                # the filenames, before adrpy managed these files.
                resumable = (
                    len(orphans) == 1
                    and orphans[0][2].status_update is None
                    and orphans[0][2].status_change is None
                    and (
                        (orphans[0][2].status_create is not None and orphans[0][2].date_create is not None)
                        or (orphans[0][2].is_migrated and header.is_migrated)
                    )
                )
                if not resumable:
                    data = {"files": orphan_files}
                    if orphan_files:
                        data["file"] = orphan_files[0]
                    raise CommandError(
                        FailureCodes.SUPERSEDE_ORPHANED_SUCCESSOR_NOT_RESUMABLE,
                        _not_resumable_reason(orphans, header),
                        data=data,
                        warnings=warnings,
                    )
                orphan_path, orphan_info, orphan_header = orphans[0]
                if orphan_header.date_create is not None:
                    validate_refdate_not_before(refdate, orphan_header.date_create)
                resumed_status = orphan_header.status_create
                successor_path = orphan_path
                successor_number = orphan_info.number
                warnings.append(
                    f"resumed: {successor_path.name} already existed and still points at this decision "
                    "-- only the predecessor was marked now; the successor itself was left as it was."
                )
            else:
                successor_number = next_number(decisions)

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

                content = build_header(config, successor) + config.template
                try:
                    # ADR001, part 3: guarantees the successor write never
                    # commits blindly if the lease was reclaimed. A lost
                    # lock here surfaces as lock-lost: nothing written yet.
                    lock.verify_still_held()
                    attempts = atomic_write_text(successor_path, content)
                except OSError as error:
                    # The FIRST write -- nothing has been written yet.
                    raise CommandError(
                        FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED,
                        f"{successor_path}: {error}",
                        data={"intended_successor": str(successor_path)},
                        warnings=warnings,
                    ) from error
                warning = retry_warning(attempts)
                if warning:
                    warnings.append(warning)

            try:
                # ADR001, part 3: this command's SECOND write (or only one,
                # when resuming) -- never commits blindly either.
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
            except (OSError, LockLostError) as error:
                # The successor already exists on disk (written above, or
                # found and resumed onto) and still holds its number, so no
                # later `new` can take it; re-running supersede on this same
                # file resumes onto it. Both OSError and LockLostError are
                # caught, so a lock lost here still names the successor
                # instead of a dataless "no write was made".
                raise CommandError(
                    FailureCodes.SUPERSEDE_WRITE_FAILED,
                    f"{path}: {error}",
                    data={
                        "predecessor": str(path),
                        "predecessor_status": "Accepted",
                        "successor": str(successor_path),
                    },
                    warnings=warnings,
                ) from error
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {
        "predecessor": str(path),
        "created": str(successor_path),
        "status": resumed_status if resume else "Proposed",
        "warnings": warnings,
    }
