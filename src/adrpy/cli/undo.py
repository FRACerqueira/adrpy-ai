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
            "Reverts an Accepted or Rejected decision to Proposed by clearing its Changed cell; the result is "
            "{file, status, warnings}, `status` being \"Proposed\", or null for a migrated decision, whose "
            "blank Created cell makes it a placeholder again (as explore reports it). The whole "
            "repository is validated first (see `adrpy check`), then the target's status and its family rules"
            " (doc/lifecycle.md: no other open Proposed member, a rejected successor's family is final); "
            "nothing is written when a rule fails."
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
        # combines the header's own flag (known since prepare)
        # with the body's own (only known now, from the streamed
        # write).
        if ctx.encoding_repaired or body_encoding_repaired:
            warnings.append(encoding_repaired_warning(path))
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

    # Canonical keyword, not the repo's configured status label; a
    # migrated decision's Created cell is blank, so clearing Changed
    # returns it to the placeholder (null, like explore's status_create).
    status = "Proposed" if ctx.header.status_create is not None else None
    return {"file": str(path), "status": status, "warnings": warnings}
