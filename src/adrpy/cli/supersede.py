"""`supersede` command: marks an Accepted decision as Superseded and
creates its successor. The successor never copies the predecessor's body (always starts from the
config's default template) and its filename suffix is unconditional,
never a collision-disambiguator. `--open` is permanently not implemented
(see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError, FailureCodes, UsageError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.lifecycle import (
    failure_codes,
    mark_superseded,
    next_number,
    prepare,
    read_target,
    scan_decisions,
    validate_refdate_not_before,
)
from adrpy.core.naming import build_filename
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, retry_warning


def _not_resumable_reason(orphans):
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
            "Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Refuses with family-member-superseded if another member of the same family has "
            "already been superseded, or family-member-pending if another member is still "
            "unresolved (Proposed) -- no write is made either way. "
            "This is two writes in sequence, not one, successor first: a failure creating the "
            "successor (supersede-successor-write-failed) means nothing was written. A failure "
            "marking the predecessor Superseded afterward (supersede-write-failed) means success=false "
            "even though the successor already exists -- that code's own `data.successor` names it, "
            "and `data.predecessor_status` is still Accepted. The successor keeps its number on disk, so "
            "no later `new` can take it; re-run with --resume to finish: it finds that successor "
            "(the existing file whose supersede suffix points back at this decision), marks only the "
            "predecessor, and says so in `warnings`. Without --resume, any existing non-Rejected "
            "successor pointing back at this decision -- left by that failure -- is refused with "
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
            "one such successor exists and it is still Proposed with its own Created status and date, and "
            "with refdate-before-history if --refdate is before that successor's creation; no write is "
            "made in any of these cases. Rejecting a still-Proposed successor directly works too: with no "
            "member of this decision's family marked Superseded, reject has nothing to revert. May also fail with "
            "family-scan-incomplete or supersede-successor-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "and successor-number allocation can't be trusted from an incomplete scan; no write was made "
            "either way. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). A file pointing back at this decision whose header does not parse "
            "is not guessed at: supersede refuses with that header's parse-failure code and names the file in data.file. "
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
        "failure_codes": failure_codes(
            "supersede",
            {
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before the predecessor's own last update date (or creation date, if never updated).",
                FailureCodes.FIELD_IS_BLANK: "--scope or --domain is a raw, non-empty flag value that is blank after stripping whitespace.",
                FailureCodes.FILE_ALREADY_EXISTS: "The successor's own resulting filename already exists on disk.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The successor's own title, once case-transformed, would produce a filename this tool could never recognize again.",
                FailureCodes.SUPERSEDE_SUCCESSOR_SCAN_INCOMPLETE: "A subdirectory under the decisions folder could not be scanned while allocating the successor's own number.",
                FailureCodes.SUPERSEDE_WRITE_FAILED: "The predecessor's own write (marking it Superseded, the SECOND of the two writes) failed -- the successor already exists (data.successor); re-run supersede with --resume to finish.",
                FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED: "The successor's own write (the FIRST of the two writes) failed -- nothing was written (data.intended_successor names the file that would have been created).",
                FailureCodes.SUPERSEDE_ORPHANED_SUCCESSOR_NOT_RESUMABLE: "--resume was given, but there is not exactly one non-Rejected successor of this decision still Proposed with its own Created status and date (data.files names what was found) -- no write was made.",
                FailureCodes.SUPERSEDE_SUCCESSOR_ALREADY_EXISTS: "A non-Rejected successor already points back at this decision (data.file/data.files name it) and --resume was not given -- no write was made; reject it to create a new successor, or re-run with --resume.",
            },
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
    ctx = prepare("supersede", flags["file"], flags)
    config, path, filename_info, header = ctx.config, ctx.path, ctx.filename_info, ctx.header
    folder, refdate, warnings = ctx.folder, ctx.refdate, ctx.warnings
    with attach_warnings(warnings):
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
            resumable = (
                len(orphans) == 1
                and orphans[0][2].status_update is None
                and orphans[0][2].status_change is None
                and orphans[0][2].status_create is not None
                and orphans[0][2].date_create is not None
            )
            if not resumable:
                data = {"files": orphan_files}
                if orphan_files:
                    data["file"] = orphan_files[0]
                raise CommandError(
                    FailureCodes.SUPERSEDE_ORPHANED_SUCCESSOR_NOT_RESUMABLE,
                    _not_resumable_reason(orphans),
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
                title=ctx.title,
                version=1,
                revision=1 if config.lenrevision > 0 else None,
                scope=ctx.scope,
                domain=ctx.domain,
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
            _record, body_encoding_repaired, attempts = mark_superseded(
                path, config, header, filename_info, successor_number, refdate
            )
            # Accurate only because the write above already succeeded.
            # ADR006V01: combines the header's own flag (known since
            # load_target) with the body's own (only known now, from
            # the streamed write).
            if ctx.encoding_repaired or body_encoding_repaired:
                warnings.append(encoding_repaired_warning(path))
        except OSError as error:
            # The successor already exists on disk (written above, or
            # found and resumed onto) and still holds its number, so no
            # later `new` can take it; re-running supersede on this same
            # file resumes onto it.
            raise CommandError(
                FailureCodes.SUPERSEDE_WRITE_FAILED,
                f"{path}: {error}. The successor ({successor_path}) was created; run supersede --resume on "
                "this decision to finish.",
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
