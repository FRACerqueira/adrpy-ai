"""`supersede` command: marks an Accepted decision as Superseded and
creates its successor. The successor never copies the predecessor's body (always starts from the
config's default template) and its filename suffix is unconditional,
never a collision-disambiguator. `--open` is permanently not implemented
(see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.header import DecisionRecord, build_header, status_row
from adrpy.core.atomic_write import normalize_newlines
from adrpy.core.fs import prepare_write
from adrpy.core.lifecycle import (
    commit_in_order,
    discard_prepared,
    failure_codes,
    next_number,
    prepare,
    prepare_mark_superseded,
)
from adrpy.core.naming import build_filename
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning


def describe():
    return {
        "name": "supersede",
        "summary": "Marks an Accepted decision Superseded and creates its successor.",
        "description": (
            "Marks an Accepted decision as Superseded and creates its successor. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "Fails with target-outside-folderadr if --file is not inside the decisions folder (folderadr). "
            "Then, before any other rule, the whole repository is validated: if it breaks a consistency rule "
            "(the ones `adrpy check` reports -- a header that does not parse, a duplicate number, a supersede "
            "link that does not point both ways, a subdirectory that could not be scanned, ...), fails with "
            "repository-inconsistent, every broken rule listed in data.errors with a repair hint. No write is "
            "made either way. "
            "Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Refuses with family-member-superseded if another member of the same family has "
            "already been superseded, or family-member-pending if another member is still "
            "unresolved (Proposed) -- no write is made either way. "
            "This is two writes, not one: both files are prepared first, then committed successor "
            "first: a failure preparing either file or creating the successor "
            "(supersede-successor-write-failed) means nothing was written. A failure "
            "marking the predecessor Superseded afterward (multi-file-write-partially-applied) means "
            "success=false even though the successor already exists -- that code's own `data.applied` "
            "names it, and `data.pending` the predecessor, still Accepted. The repository is then "
            "inconsistent (successor-without-predecessor), so every command refuses it until it is repaired "
            "by hand: remove the successor (just created from the template) and run supersede again, or mark "
            "the predecessor Superseded in its Superseded cell. "
            "The successor's own title -- the predecessor's own filename segment, "
            "re-validated before use, unless --title overrides it (see its own argument description) -- "
            "may fail with field-contains-forbidden-character if it carries '|', a line-break-like "
            "character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control character; the successor's "
            "title lands inside an actual filename component, not just a header-table cell), or consists "
            "entirely of "
            "whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a "
            "value raw, which can collide with the filename's own separator and produce a successor the "
            "tool can never recognize again; no write is made. Fails with one of still-proposed, "
            "already-rejected, or already-superseded (the target's own "
            "current status makes Superseded unreachable from here) if the target isn't eligible -- no "
            "write is made. Fails with file-already-exists (data.file names it) if the successor's own "
            "resulting filename already exists on disk when it is created -- no write is made either."
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
        "failure_codes": failure_codes(
            "supersede",
            {
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before the predecessor's own last update date (or creation date, if never updated).",
                FailureCodes.FIELD_IS_BLANK: "--scope or --domain is a raw, non-empty flag value that is blank after stripping whitespace.",
                FailureCodes.FILE_ALREADY_EXISTS: "The successor's own resulting filename already exists on disk.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The successor's own title, once case-transformed, would produce a filename this tool could never recognize again.",
                FailureCodes.MULTI_FILE_WRITE_PARTIALLY_APPLIED: "The predecessor's own write (marking it Superseded, the SECOND of the two writes) failed -- the successor already exists (data.applied names it, data.pending the predecessor); the repository is then inconsistent until repaired by hand (remove the successor and supersede again, or mark the predecessor Superseded with the exact row in data.repair).",
                FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED: "Preparing either file, or creating the successor (the FIRST of the two commits), failed -- nothing was written (data.intended_successor names the file that would have been created).",
            },
        ),
    }


def run(args):
    flags = parse_flags(
        args,
        required=("file",),
        optional=("domain", "scope", "refdate", "title"),
        aliases={"f": "file", "d": "domain", "s": "scope", "r": "refdate", "t": "title"},
    )
    ctx = prepare("supersede", flags["file"], flags)
    config, path, filename_info, header = ctx.config, ctx.path, ctx.filename_info, ctx.header
    folder, refdate, warnings = ctx.folder, ctx.refdate, ctx.warnings
    with attach_warnings(warnings):
        # The repository was validated and no member of this decision's
        # family is Superseded (family-member-superseded), so no successor
        # of it that is not Rejected exists either
        # (successor-without-predecessor otherwise): there is nothing to
        # resume or collide with. The successor's number comes after every
        # decision in the same snapshot.
        successor_number = next_number(
            [(decision.scheme, decision.name, decision.path) for decision in ctx.snapshot.decisions]
        )

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
        content = build_header(config, successor) + config.template

        # Every file is prepared before any is committed: a failure up to
        # here leaves nothing written and no temp file behind.
        prepared = []
        try:
            prepared.append(prepare_write(successor_path, normalize_newlines(content).encode("utf-8")))
            _record, body_encoding_repaired, predecessor_prepared = prepare_mark_superseded(
                path, config, header, filename_info, successor_number, refdate
            )
            prepared.append(predecessor_prepared)
        except BaseException as error:
            discard_prepared(prepared)
            if not isinstance(error, OSError):
                raise
            raise CommandError(
                FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED,
                f"{error}. Nothing was written.",
                data={"intended_successor": str(successor_path)},
                warnings=warnings,
            ) from error

        # ADR006V01: combines the header's own flag (known since
        # prepare) with the body's own (only known now, from the
        # streamed read); reported only once the predecessor is written.
        predecessor_warnings = []
        if ctx.encoding_repaired or body_encoding_repaired:
            predecessor_warnings.append(encoding_repaired_warning(path))
        # Successor first, created exclusively: a name taken since the
        # scan is refused with nothing written. Then the predecessor; if
        # that fails, the successor is on disk and the repository is
        # inconsistent until repaired by hand.
        try:
            commit_in_order(
                [(prepared[0], True, []), (predecessor_prepared, False, predecessor_warnings)],
                warnings,
                hint=(
                    "The repository is now inconsistent (adrpy check names it): remove the successor (just "
                    "created from the template) and run supersede again, or mark this decision Superseded by "
                    "hand (data.repair)."
                ),
                repair={
                    "file": str(path),
                    "row": status_row(
                        config,
                        config.headertitlestatussuperseded,
                        "Superseded",
                        refdate,
                        suffix=f" : {successor_number:0{config.lenseq}d}",
                    ),
                },
            )
        except FileExistsError as error:
            raise CommandError(
                FailureCodes.FILE_ALREADY_EXISTS,
                f"File already exists: {filename}",
                data={"file": filename},
                warnings=warnings,
            ) from error
        except OSError as error:
            # The first commit, the successor's: nothing has been written.
            raise CommandError(
                FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED,
                f"{successor_path}: {error}",
                data={"intended_successor": str(successor_path)},
                warnings=warnings,
            ) from error

    # Canonical keyword, not the repo's configured status label.
    return {
        "predecessor": str(path),
        "created": str(successor_path),
        "status": "Proposed",
        "warnings": warnings,
    }
