"""`supersede` command: marks an Accepted decision as Superseded and
creates its successor. The successor never copies the predecessor's body (always starts from the
config's default template) and its filename suffix is unconditional,
never a collision-disambiguator. `--open` is permanently not implemented
(see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.config import LENSEQ_MAX
from adrpy.core.consistency import note_shared_numbers
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
    widening_hint,
)
from adrpy.core.naming import build_filename
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning


def describe():
    return {
        "name": "supersede",
        "summary": "Marks an Accepted decision Superseded and creates its successor.",
        "description": (
            "Marks an Accepted decision (or a migrated placeholder) Superseded and creates its successor, status Proposed, in a new "
            "family whose filename ends with the predecessor's number (--NNN). The whole repository and the "
            "family rules in doc/lifecycle.md are checked first, and both files are prepared before either is"
            " written. The successor is written first; if only it could be written, the failure names what "
            "was and was not written and the header row to put in the predecessor by hand (data.applied, "
            "data.pending, data.repair)."
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
                    "Title for the successor; defaults to the predecessor's title as its file name spells it "
                    "(unlike --scope/--domain, which default to the header's values, editing the header does "
                    "not change this default). Cannot contain '|' or a line-break-like character, or a "
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
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER: "--title/--scope/--domain, or the title taken from the predecessor's own filename, contains '|', a line-break-like character, or (title only) a filesystem-unsafe character; or the title consists entirely of whitespace/'_'/'-'.",
                FailureCodes.FIELD_IS_BLANK: "--scope or --domain is a raw, non-empty flag value that is blank after stripping whitespace.",
                FailureCodes.LENSEQ_TOO_SMALL_FOR_NEW_NUMBER: "The successor's number (data.new_number) has more digits than lenseq (data.lenseq); detail gives the `adrpy config --lenseq` that widens it, or says it is already at its maximum. Nothing was written.",
                FailureCodes.FILE_ALREADY_EXISTS: "The successor's own resulting filename already exists on disk.",
                FailureCodes.FILENAME_TOO_LONG: "The successor's own title makes a file name longer than the filesystem allows once the temp file's suffix is added (data.filename) -- nothing was written; shorten --title. Also when --file's own name is longer than the 234 bytes this tool can rewrite (then rename it by hand to a shorter title part, keeping its number, version, revision and any --NNN suffix).",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The successor's own title, once case-transformed, would produce a filename this tool could never recognize again.",
                FailureCodes.MULTI_FILE_WRITE_PARTIALLY_APPLIED: "The predecessor's own write (marking it Superseded, the SECOND of the two writes) failed -- the successor already exists (data.applied names it, data.pending the predecessor); the repository is then inconsistent until repaired by hand (remove the successor and supersede again, or mark the predecessor Superseded with the exact row in data.repair).",
                FailureCodes.INTERRUPTED: "Interrupted (Ctrl+C) after the successor was created but before the predecessor was marked Superseded -- same data as multi-file-write-partially-applied (data.applied, data.pending, data.repair). Once both are written, data.applied names both, data.pending is empty and there is no data.repair (the repository is consistent). What was written is read from the disk, so an interrupt right after a write counts it. An interrupt before the first write is reported without data.",
                FailureCodes.SUPERSEDE_SUCCESSOR_WRITE_FAILED: "Preparing either file, or creating the successor (the FIRST of the two commits), failed -- no decision was changed (data.intended_successor names the file that would have been created, data.failed_file the one whose write failed). If the empty reservation of that name could not be removed, it is left as a 0-byte file that check names: remove it.",
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
        # collide with. The successor's number comes after every
        # decision in the same snapshot.
        successor_number = next_number(
            [(decision.scheme, decision.name, decision.path) for decision in ctx.snapshot.decisions]
        )
        if len(str(successor_number)) > config.lenseq:
            raise CommandError(
                FailureCodes.LENSEQ_TOO_SMALL_FOR_NEW_NUMBER,
                f"New number {successor_number} does not fit in lenseq={config.lenseq}."
                + widening_hint(
                    "lenseq", len(str(successor_number)), LENSEQ_MAX, "this repository has no room for another decision"
                ),
                data={"new_number": successor_number, "lenseq": config.lenseq},
                warnings=warnings,
            )

        successor = DecisionRecord(
            number=successor_number,
            # Defaults to the predecessor's own FILENAME segment
            # (already case-transformed), not its header's prose title.
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
                data={"intended_successor": str(successor_path), "failed_file": str(path if prepared else successor_path)},
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
                data={"intended_successor": str(successor_path), "failed_file": str(successor_path)},
                warnings=warnings,
            ) from error
        note_shared_numbers(
            warnings, ctx.snapshot, config, [(successor_number, True), (filename_info.number, False)]
        )

    # Canonical keyword, not the repo's configured status label.
    return {
        "predecessor": str(path),
        "created": str(successor_path),
        "status": "Proposed",
        "warnings": warnings,
    }
