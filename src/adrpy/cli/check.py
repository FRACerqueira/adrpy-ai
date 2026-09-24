"""`check` command: validates the whole repository, read-only."""

from adrpy.core.args import parse_flags
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.consistency import validate_repository
from adrpy.core.errors import FailureCodes, build_failure_codes
from adrpy.core.header import SHARED_FAILURE_CODES as HEADER_FAILURE_CODES
from adrpy.core.lifecycle import resolve_target_and_config
from adrpy.core.security import resolve_within

_ERROR_CODES = {
    FailureCodes.MERGE_CONFLICT_MARKERS: "data.errors[].code: git merge-conflict markers in a file's 12 header lines (reported alone for that file).",
    FailureCodes.NO_HEADER: "data.errors[].code: a file with an ADR name has no header at all (run migrate if it predates the tool).",
    FailureCodes.INVALID_HEADER: "data.errors[].code: a file's header does not parse; `detail` names the parse failure.",
    FailureCodes.INVALID_STATUS_COMBINATION: "data.errors[].code: a header's Created/Changed/Superseded cells form a combination no command writes.",
    FailureCodes.DUPLICATE_NUMBER: "data.errors[].code: two files share number, version and revision (a missing revision counts as 0).",
    FailureCodes.PENDING_DUPLICATE: "data.errors[].code: a family has more than one open Proposed decision (a migrated placeholder does not count).",
    FailureCodes.PENDING_NOT_LIVE: "data.errors[].code: a Proposed decision is locked by a newer family member that is not Rejected.",
    FailureCodes.SUPERSEDED_DUPLICATE: "data.errors[].code: a family has more than one Superseded member.",
    FailureCodes.SUPERSEDED_NOT_LIVE: "data.errors[].code: a Superseded decision is locked by a newer family member that is not Rejected.",
    FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR: "data.errors[].code: a Superseded cell points at no existing, non-Rejected successor whose filename suffix names this decision.",
    FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR: "data.errors[].code: a non-Rejected successor has no predecessor whose Superseded cell points back at it.",
    FailureCodes.MULTIPLE_LIVE_SUCCESSORS: "data.errors[].code: more than one non-Rejected successor names the same predecessor.",
    FailureCodes.REJECTED_SUCCESSOR_FAMILY_NOT_FINAL: "data.errors[].code: a member of a Rejected successor's family is not Rejected.",
    FailureCodes.SCAN_INCOMPLETE: "data.errors[].code: a directory or decision file under the decisions folder could not be read.",
}

# The reason an invalid-header entry gives: its `detail` starts with one of
# these codes (the same data.errors the file commands and new report).
_HEADER_DETAIL_CODES = {
    code: f"data.errors[].detail of an invalid-header entry starts with this code: {text[0].lower()}{text[1:]}"
    for code, text in HEADER_FAILURE_CODES.items()
}


def describe():
    return {
        "name": "check",
        "summary": "Validates every decision in the repository and lists every inconsistency found.",
        "description": (
            "Validates the whole repository, read-only: every file with an ADR name under the decisions "
            "folder (any other .md is ignored) is checked against the consistency rules in doc/lifecycle.md. "
            "Succeeds with the number of decisions when every rule holds; otherwise fails with "
            "repository-inconsistent, every broken rule listed in data.errors (code, file, related_files, "
            "detail, hint), sorted by file."
        ),
        "arguments": [
            {
                "name": "path",
                "alias": "-p",
                "type": "string",
                "required": True,
                "description": "Repository root directory (must contain adr-config.adrplus).",
            },
        ],
        "failure_codes": build_failure_codes(
            {
                FailureCodes.REPOSITORY_INCONSISTENT: "At least one consistency rule is broken; data.errors lists every one.",
            },
            _ERROR_CODES,
            _HEADER_DETAIL_CODES,
            {
                FailureCodes.TARGET_DIRECTORY_NOT_FOUND: "--path does not point to an existing directory.",
                FailureCodes.CONFIG_NOT_FOUND: "--path's own directory has no adr-config.adrplus.",
                FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
                FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
            },
            CONFIG_FAILURE_CODES,
        ),
    }


def run(args):
    path = parse_flags(args, required=("path",), aliases={"p": "path"})["path"]
    target, _config_path, config = resolve_target_and_config(path)
    folder = resolve_within(target, config.folderadr)
    snapshot = validate_repository(folder, config)
    return {"decisions": len(snapshot.decisions), "warnings": []}
