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
from adrpy.core.consistency import SUPERSEDED
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.family import is_successor
from adrpy.core.header import status_row
from adrpy.core.lifecycle import (
    commit_in_order,
    discard_prepared,
    failure_codes,
    prepare,
    prepare_status_field_rewrite,
    rewrite_status_field,
)
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, retry_warning


def describe():
    return {
        "name": "reject",
        "summary": "Marks a Proposed decision Rejected.",
        "description": (
            "Marks a Proposed decision as Rejected. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "Fails with target-outside-folderadr if --file is not inside the decisions folder (folderadr). "
            "Then, before any other rule, the whole repository is validated: if it breaks a consistency rule "
            "(the ones `adrpy check` reports -- a header that does not parse, a duplicate number, a supersede "
            "link that does not point both ways, a subdirectory that could not be scanned, ...), fails with "
            "repository-inconsistent, every broken rule listed in data.errors with a repair hint. No write is "
            "made either way. "
            "If this decision is itself a successor "
            "(created by `supersede`), the predecessor's Superseded status is reverted FIRST, before "
            "this decision's own status is written -- the result's `undone_predecessor` names that file "
            "when this happens, or is null otherwise. In a consistent repository that predecessor always "
            "exists: a successor that is not Rejected with no predecessor pointing back at it is itself a "
            "broken rule (successor-without-predecessor). This is two writes, not one: both files are prepared "
            "first, then committed predecessor first, and every failure up to and including the "
            "predecessor's own commit leaves NOTHING committed at all: reject-predecessor-write-failed (a "
            "real OSError preparing either file or committing the predecessor) means no write was made and "
            "the call is safely retryable from scratch. Only multi-file-write-partially-applied is a genuine "
            "partial success: the predecessor was already reverted for real when committing THIS "
            "decision's own Rejected status then failed -- `data.applied` names the file already "
            "reverted, `data.pending` this decision. The repository is then inconsistent "
            "(successor-without-predecessor), so every command refuses it until it is repaired by hand: "
            "mark this decision Rejected in its Changed cell. "
            "The target's own title/scope/domain "
            "(re-read from its header cells, not flags) are re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character), or consists entirely of whitespace/'_'/'-'; no write made in that case either. "
            "BEFORE any write, fails with one "
            "of already-accepted, already-rejected, or already-superseded "
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
        "failure_codes": failure_codes(
            "reject",
            {
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before this decision's own creation date.",
                FailureCodes.REJECT_PREDECESSOR_WRITE_FAILED: "Preparing either file, or committing the predecessor's reverted Superseded status, failed with a real OSError -- no write was made.",
                FailureCodes.MULTI_FILE_WRITE_PARTIALLY_APPLIED: "The predecessor's Superseded status was already reverted for real, but committing this decision's own Rejected status then failed -- data.applied names the file already reverted, data.pending this decision; the repository is then inconsistent until this decision is marked Rejected by hand, with the exact row in data.repair.",
            },
        ),
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("refdate",), aliases={"f": "file", "r": "refdate"})
    ctx = prepare("reject", flags["file"], flags)
    config, path, filename_info, header = ctx.config, ctx.path, ctx.filename_info, ctx.header
    refdate, warnings = ctx.refdate, ctx.warnings
    with attach_warnings(warnings):
        # Round-36 retraction of the original order (this decision's own
        # write, then the predecessor's): reverting the predecessor
        # FIRST means every failure up to and including that write
        # leaves nothing committed at all -- always safely retryable
        # from scratch, instead of risking a predecessor stuck
        # Superseded forever with no command able to touch it again
        # (status_change is a terminal state everywhere else in this
        # codebase; there is no "unsupersede" verb).
        undone_predecessor = None
        predecessor = None
        if is_successor(filename_info):
            # The member of the predecessor's family whose Superseded cell
            # names this decision -- not necessarily its latest member (an
            # earlier `version` bump). The repository was validated: this
            # decision is not Rejected, so exactly that member exists
            # (successor-without-predecessor otherwise).
            predecessor = next(
                decision
                for decision in ctx.snapshot.by_number.get(filename_info.superseded_from, ())
                if decision.state == SUPERSEDED and decision.successor_ref == filename_info.number
            )

        if predecessor is not None:
            _revert_then_reject(ctx, (predecessor.name, predecessor.header, predecessor.path))
            undone_predecessor = str(predecessor.path)
        else:
            _record, body_encoding_repaired, attempts = rewrite_status_field(
                path, config, header, filename_info, field="update", status="Rejected", refdate=refdate
            )
            # Accurate only because the write above already succeeded --
            # the warning claims the file was rewritten. ADR006V01:
            # combines the header's own flag (known since prepare)
            # with the body's own (only known now, from the streamed
            # write).
            if ctx.encoding_repaired or body_encoding_repaired:
                warnings.append(encoding_repaired_warning(path))
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"file": str(path), "status": "Rejected", "undone_predecessor": undone_predecessor, "warnings": warnings}


def _revert_then_reject(ctx, predecessor):
    """The two writes of rejecting a successor: the predecessor's
    Superseded status reverted, then this decision's own Rejected status.
    Both files are prepared before either is committed, so a failure up
    to there leaves nothing written. They are committed predecessor
    FIRST: a failure of that commit also leaves nothing written, and one
    of this decision's commit after it is reported as
    multi-file-write-partially-applied. That leaves this decision a
    successor with no predecessor pointing at it, which the validator
    refuses (successor-without-predecessor) until it is repaired by
    hand."""
    config, path, filename_info, header = ctx.config, ctx.path, ctx.filename_info, ctx.header
    warnings = ctx.warnings
    pred_parsed, pred_header, pred_path = predecessor
    prepared = []
    try:
        # pred_header already comes from the validated snapshot's own
        # read (core/consistency, via read_header_lines_with_report) -- no
        # separate read needed for the header portion. It parsed, so
        # whatever that read replaced did not affect the status read
        # from it -- only the BODY's own encoding status (ADR006V01,
        # known only once the streamed read has run) can still need the
        # warning.
        _record, pred_body_encoding_repaired, pred_prepared = prepare_status_field_rewrite(
            pred_path, config, pred_header, pred_parsed, field="change", status=None, refdate=None
        )
        prepared.append(pred_prepared)
        _record, body_encoding_repaired, own_prepared = prepare_status_field_rewrite(
            path, config, header, filename_info, field="update", status="Rejected", refdate=ctx.refdate
        )
        prepared.append(own_prepared)
    except BaseException as error:
        discard_prepared(prepared)
        if not isinstance(error, OSError):
            raise
        raise CommandError(
            FailureCodes.REJECT_PREDECESSOR_WRITE_FAILED,
            f"{error}. No write was made.",
            warnings=warnings,
        ) from error

    pred_warnings = [encoding_repaired_warning(pred_path)] if pred_body_encoding_repaired else []
    own_warnings = []
    if ctx.encoding_repaired or body_encoding_repaired:
        own_warnings.append(encoding_repaired_warning(path))
    try:
        commit_in_order(
            [(pred_prepared, False, pred_warnings), (own_prepared, False, own_warnings)],
            warnings,
            hint="The repository is now inconsistent (adrpy check names it): mark this decision Rejected by hand "
            "to finish (data.repair).",
            repair={
                "file": str(path),
                "row": status_row(config, config.headertitlestatuschanged, "Rejected", ctx.refdate),
            },
        )
    except OSError as error:
        # The predecessor's commit, the first: nothing has been written.
        raise CommandError(
            FailureCodes.REJECT_PREDECESSOR_WRITE_FAILED,
            f"{pred_path}: {error}. No write was made.",
            warnings=warnings,
        ) from error
