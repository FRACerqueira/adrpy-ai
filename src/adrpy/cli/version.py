"""`version` command: creates a new major version of an Accepted/Rejected
decision. `--open` is permanently not implemented (see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_chunks, atomic_write_text
from adrpy.core.lifecycle import failure_codes, prepare, stream_normalized_body_chunks
from adrpy.core.naming import build_filename
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_source_warning, retry_warning


def describe():
    return {
        "name": "version",
        "summary": "Creates a new major version of an Accepted/Rejected decision.",
        "description": (
            "Creates a new major version of an Accepted/Rejected decision. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "May also fail with family-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "can't be trusted from an incomplete scan; no write was made. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). "
            "The target's own title (re-read "
            "from its header cell, not a flag) is re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character; title lands inside an actual filename component, not just a header-table cell), or "
            "consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls "
            "back to echoing such a value raw, which can collide with the filename's own separator and "
            "produce a successor file the tool can never recognize again. Fails with family-not-found if "
            "this decision's own family can't be resolved, or lenversion-too-small-for-new-version "
            "(data.new_version/data.lenversion) if the next version number doesn't fit the configured "
            "width -- no write is made either way. Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Fails with supersede-not-finished if this decision belongs to the successor of an interrupted supersede whose predecessor doesn't point at it yet -- run supersede --resume on the predecessor first, or reject it. Fails with rejected-successor-is-final if the "
            "target belongs to the family of a successor that was rejected. Fails with one of still-proposed, "
            "already-superseded, not-proposed, or unexpected-status if the target isn't eligible, or "
            "family-member-superseded/family-member-pending if another member of the same family has "
            "already been superseded or is still unresolved (Proposed). Fails with file-already-exists "
            "(data.file names it) if the resulting filename already exists on disk, or if any file of "
            "this family already holds the number it would create -- whatever its title, whether or not "
            "its header parses. No write is made in "
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
                "name": "domain",
                "alias": "-d",
                "type": "string",
                "required": False,
                "description": (
                    "Domain for the new version; defaults to this decision's own value. Cannot contain "
                    "'|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    "Scope for the new version; defaults to this decision's own value. Cannot contain "
                    "'|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
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
            {
                "name": "empty",
                "alias": "-e",
                "type": "switch",
                "required": False,
                # Presence-only (`--empty` with no value, like a getopt
                # flag), not "boolean" -- `--empty true`/`--empty false`
                # both fail with "Unknown argument", unlike
                # `config --disableplugins`, which does take a value.
                "description": (
                    "Start from the default template instead of carrying the source's content forward. "
                    "Presence-only: pass just '--empty' with no value; do not pass '--empty true/false'."
                ),
            },
        ],
        "failure_codes": failure_codes(
            "version",
            {
                FailureCodes.FAMILY_NOT_FOUND: "This decision's own family could not be resolved.",
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before this decision's own last update date (or creation date, if never updated).",
                FailureCodes.FIELD_IS_BLANK: "--scope or --domain is a raw, non-empty flag value that is blank after stripping whitespace.",
                FailureCodes.FILE_ALREADY_EXISTS: "The new version's number is already held by a file of this family (any title, header valid or not), or its resulting filename already exists -- data.file names it.",
                FailureCodes.LENVERSION_TOO_SMALL_FOR_NEW_VERSION: "The next version number does not fit in the configured lenversion width.",
                FailureCodes.TITLE_PRODUCES_UNRECOGNIZABLE_FILENAME: "The new version's own title, once case-transformed, would produce a filename this tool could never recognize again.",
            },
        ),
    }


def run(args):
    flags = parse_flags(
        args,
        required=("file",),
        optional=("domain", "scope", "refdate"),
        switches=("empty",),
        aliases={"f": "file", "d": "domain", "s": "scope", "r": "refdate", "e": "empty"},
    )
    ctx = prepare("version", flags["file"], flags)
    config, path, folder, warnings = ctx.config, ctx.path, ctx.folder, ctx.warnings
    new_version = ctx.new_version
    with attach_warnings(warnings):
        # version never rewrites its own source (only its BODY is
        # carried into a newly created file) -- encoding_repaired_
        # source_warning's "the file has been rewritten" claim is never
        # true here. ADR006V01: the body is no longer read at all
        # unless/until the write below actually streams it, so this
        # warning (which is specifically about the BODY's own decode,
        # not just the header's) can only be finalized once that
        # streamed write has happened -- combined with `encoding_
        # repaired` (the header's own flag, already known here) right
        # after the write, not right away.

        # Unlike `new`, an omitted --scope/--domain defaults to this
        # decision's own current value, not empty (prepare's
        # "flag-or-header") -- also when branching off an older member
        # whose newer ones were rejected (Round 41).
        record = DecisionRecord(
            number=ctx.filename_info.number,
            title=ctx.title,
            version=new_version,
            revision=1 if config.lenrevision > 0 else None,
            scope=ctx.scope,
            domain=ctx.domain,
            status_create="Proposed",
            date_create=ctx.refdate,
        )

        filename = build_filename(config, record)
        # The filename decides numbering, counting every file: a version
        # number already held by any file of this family is taken, never
        # given to a second file.
        taken = next((entry[2] for entry in ctx.members + ctx.ignored if entry[0].version == new_version), None)
        if taken is not None:
            raise CommandError(
                FailureCodes.FILE_ALREADY_EXISTS,
                f"Version {new_version} is already held by {taken.name}.",
                data={"file": taken.name},
                warnings=warnings,
            )
        new_path = resolve_within(folder, filename)
        if new_path.exists():
            raise CommandError(
                FailureCodes.FILE_ALREADY_EXISTS,
                f"File already exists: {filename}",
                data={"file": filename},
                warnings=warnings,
            )

        # ADR006V01: --empty uses config.template (schema-bounded, safe
        # in memory, unchanged); otherwise the SOURCE's own body is
        # streamed straight from `path` into the new file, without
        # ever holding it in memory. body_encoding_repaired stays
        # False (the default a fresh report dict would carry) when
        # --empty means the body is never read at all.
        header_text = build_header(config, record)
        if flags.get("empty"):
            attempts = atomic_write_text(new_path, header_text + config.template)
            body_encoding_repaired = False
        else:
            body_report = {}

            def _chunks(path=path, header_text=header_text, body_report=body_report):
                yield header_text.encode("utf-8")
                yield from stream_normalized_body_chunks(path, body_report)

            attempts = atomic_write_chunks(new_path, _chunks)
            body_encoding_repaired = body_report["encoding_repaired"]
        if ctx.encoding_repaired or body_encoding_repaired:
            warnings.append(encoding_repaired_source_warning(path))
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"created": str(new_path), "status": "Proposed", "warnings": warnings}
