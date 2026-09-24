"""`approve` command: marks a Proposed decision as Accepted."""

from adrpy.core.args import parse_flags
from adrpy.core.errors import FailureCodes
from adrpy.core.lifecycle import failure_codes, prepare, rewrite_status_field
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, retry_warning


def describe():
    return {
        "name": "approve",
        "summary": "Marks a Proposed decision Accepted.",
        "description": (
            "Marks a Proposed decision as Accepted. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "Fails with target-outside-folderadr if --file is not inside the decisions folder (folderadr). "
            "Then, before any other rule, the whole repository is validated: if it breaks a consistency rule "
            "(the ones `adrpy check` reports -- a header that does not parse, a duplicate number, a supersede "
            "link that does not point both ways, a subdirectory that could not be scanned, ...), fails with "
            "repository-inconsistent, every broken rule listed in data.errors with a repair hint. No write is "
            "made either way. "
            "The target's own title/scope/"
            "domain (re-read from its header cells, not flags) are re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character), or consists entirely of whitespace/'_'/'-' -- this command never renames the file "
            "itself, but rewrites its header with the same fields a later rename-capable command "
            "(version/revise/supersede) would also need to trust. Fails with one of "
            "already-accepted, already-rejected, or already-superseded "
            "(the target's own current status makes Accepted unreachable from here) if the target isn't "
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
            "approve",
            {
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.REFDATE_BEFORE_HISTORY: "--refdate is before this decision's own creation date.",
            },
        ),
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("refdate",), aliases={"f": "file", "r": "refdate"})
    ctx = prepare("approve", flags["file"], flags)
    path, warnings = ctx.path, ctx.warnings
    with attach_warnings(warnings):
        _record, body_encoding_repaired, attempts = rewrite_status_field(
            path, ctx.config, ctx.header, ctx.filename_info, field="update", status="Accepted", refdate=ctx.refdate
        )
        # encoding_repaired_warning claims "the file has been rewritten
        # ... bytes are now lost" -- only true once the write above has
        # actually happened, not at read time (an eligibility check
        # could still have failed first). ADR006V01: combines the
        # header's own flag (known since load_target, above) with the
        # body's own (only known now, once the streamed write has
        # actually read it) -- either half being lossy loses bytes on
        # this rewrite.
        if ctx.encoding_repaired or body_encoding_repaired:
            warnings.append(encoding_repaired_warning(path))
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # Canonical keyword, matching explore's own status_create/status_update
    # -- not the repo's configured status label.
    return {"file": str(path), "status": "Accepted", "warnings": warnings}
