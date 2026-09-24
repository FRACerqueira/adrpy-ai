"""`undo` command: reverts a decision's update status back to blank. No
--refdate -- clears the "Changed" row entirely rather than recording a
new transition.
"""

from adrpy.core.args import parse_flags
from adrpy.core.lifecycle import failure_codes, prepare, rewrite_status_field
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, retry_warning


def describe():
    return {
        "name": "undo",
        "summary": "Reverts a decision's Accepted/Rejected status back to Proposed.",
        "description": (
            "Reverts a decision's Accepted/Rejected status back to Proposed. "
            "May fail with file-not-found if --file does not point to an existing file (a bare name with "
            "no extension gets '.md' appended before this check), or cannot-determine-root-path if no "
            "adr-config.adrplus is found by walking up from it -- no write is attempted either way. "
            "Fails with target-outside-folderadr if --file is not inside the decisions folder (folderadr). "
            "Then, before any other rule, the whole repository is validated: if it breaks a consistency rule "
            "(the ones `adrpy check` reports -- a header that does not parse, a duplicate number, a supersede "
            "link that does not point both ways, a subdirectory that could not be scanned, ...), fails with "
            "repository-inconsistent, every broken rule listed in data.errors with a repair hint. No write is "
            "made either way. "
            "A title, scope or domain in the target's header that breaks the free-text rules ('|', a "
            "line-break-like character, or -- title only -- a filesystem-unsafe character (`<>:\"/\\|?*` or a "
            "control character) or nothing but whitespace/'_'/'-') makes the header invalid: one of "
            "repository-inconsistent's data.errors (invalid-header). Fails with one of "
            "still-proposed or already-superseded if the target isn't eligible, or "
            "family-member-superseded/family-member-pending if another member of the same family has "
            "already been superseded or is still unresolved (Proposed). Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Fails with "
            "rejected-successor-is-final if the target belongs to the family of a successor that was "
            "rejected -- the end of its line. No write is made in any of "
            "these cases."
        ),
        "arguments": [
            {
                "name": "file",
                "alias": "-f",
                "type": "string",
                "required": True,
                "description": "Path to the decision file. A bare name with no extension gets '.md' appended.",
            },
        ],
        "failure_codes": failure_codes("undo", {}),
    }


def run(args):
    flags = parse_flags(args, required=("file",), aliases={"f": "file"})
    ctx = prepare("undo", flags["file"], flags)
    path, warnings = ctx.path, ctx.warnings
    with attach_warnings(warnings):
        _record, body_encoding_repaired, attempts = rewrite_status_field(
            path, ctx.config, ctx.header, ctx.filename_info, field="update", status=None, refdate=None
        )
        # Accurate only because the write above already succeeded --
        # the warning claims the file was rewritten. ADR006V01:
        # combines the header's own flag (known since load_target)
        # with the body's own (only known now, from the streamed
        # write).
        if ctx.encoding_repaired or body_encoding_repaired:
            warnings.append(encoding_repaired_warning(path))
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"file": str(path), "status": "Proposed", "warnings": warnings}
