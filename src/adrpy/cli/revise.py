"""`revise` command: creates a new revision (minor change) of an
Accepted/Rejected decision. Unlike `version`, revise has no --scope/
--domain and no --empty -- it always carries the source's content
forward, and its scope/domain come from the TARGET file's own header,
not the latest member's. --open is permanently not implemented (see
`new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_chunks
from adrpy.core.lifecycle import failure_codes, prepare, stream_normalized_body_chunks
from adrpy.core.naming import build_filename
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_source_warning, retry_warning


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
            "Fails with target-outside-folderadr if --file is not inside the decisions folder (folderadr). "
            "Then, before any other rule, the whole repository is validated: if it breaks a consistency rule "
            "(the ones `adrpy check` reports -- a header that does not parse, a duplicate number, a supersede "
            "link that does not point both ways, a subdirectory that could not be scanned, ...), fails with "
            "repository-inconsistent, every broken rule listed in data.errors with a repair hint. No write is "
            "made either way. "
            "The target's own title/scope/"
            "domain (all re-read from its header cells, not flags -- this command has none for scope/"
            "domain) are re-validated before use -- may fail with field-contains-forbidden-character if a "
            "hand-edited or migrated source file carries '|', a line-break-like character in any of the "
            "three, a filesystem-unsafe character in title specifically (`<>:\"/\\|?*` or a control "
            "character; title lands inside an actual filename component, not just a header-table cell), or "
            "title consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step "
            "falls back to echoing such a value raw, which can collide with the filename's own separator "
            "and produce a file the tool can never recognize again. Fails with family-not-found if this "
            "decision's own family can't be resolved, or lenrevision-too-small-for-new-revision "
            "(data.new_revision/data.lenrevision) if the next revision number -- the one after the highest "
            "revision this version already holds, whatever file holds it -- doesn't fit the configured "
            "width -- no write is made either way. Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Fails with rejected-successor-is-final if the "
            "target belongs to the family of a successor that was rejected. Fails with one of still-proposed, "
            "already-superseded if the target isn't eligible, or "
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
                    "this decision's own last update date (or creation date, if never updated) "
                    "(refdate-invalid-format/refdate-in-future/refdate-before-history)."
                ),
            },
        ],
        "failure_codes": failure_codes(
            "revise",
            {
                FailureCodes.FAMILY_NOT_FOUND: "This decision's own family could not be resolved.",
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before this decision's own last update date (or creation date, if never updated).",
                FailureCodes.FILE_ALREADY_EXISTS: "The new revision's own resulting filename already exists on disk (data.file names it).",
                FailureCodes.LENREVISION_TOO_SMALL_FOR_NEW_REVISION: "The next revision number does not fit in the configured lenrevision width.",
                FailureCodes.REVISION_NOT_CONFIGURED: "This repository's config has lenrevision == 0.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The new revision's own title, once case-transformed, would produce a filename this tool could never recognize again.",
            },
        ),
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("refdate",), aliases={"f": "file", "r": "refdate"})
    ctx = prepare("revise", flags["file"], flags)
    config, path, folder, header, warnings = ctx.config, ctx.path, ctx.folder, ctx.header, ctx.warnings
    with attach_warnings(warnings):
        # revise never rewrites its own source either -- see version.py's
        # own comment: ADR006V01 defers this warning until after the
        # write below, since the body is no longer read until then.
        record = DecisionRecord(
            number=ctx.filename_info.number,
            title=header.title,
            version=ctx.filename_info.version,
            revision=ctx.new_revision,
            scope=header.scope,
            domain=header.domain,
            status_create="Proposed",
            date_create=ctx.refdate,
        )

        filename = build_filename(config, record)
        new_path = resolve_within(folder, filename)

        # ADR006V01: streams the source's own body straight from
        # `path` into the new file, without ever holding it in memory.
        header_text = build_header(config, record)
        body_report = {}

        def _chunks(path=path, header_text=header_text, body_report=body_report):
            yield header_text.encode("utf-8")
            yield from stream_normalized_body_chunks(path, body_report)

        try:
            attempts = atomic_write_chunks(new_path, _chunks, exclusive=True)
        except FileExistsError as error:
            raise CommandError(
                FailureCodes.FILE_ALREADY_EXISTS,
                f"File already exists: {filename}",
                data={"file": filename},
                warnings=warnings,
            ) from error
        if ctx.encoding_repaired or body_report["encoding_repaired"]:
            warnings.append(encoding_repaired_source_warning(path))
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"created": str(new_path), "status": "Proposed", "warnings": warnings}
