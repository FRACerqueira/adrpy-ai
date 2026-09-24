"""`explore` command: read-only inventory of every decision file.
Recognizes BOTH naming schemes via `parse_any_filename` -- a file
matching neither still appears in the report, never dropped silently. A
distinct mechanism, is_within (core/security.py), CAN still exclude a
candidate whose real path escapes the repository boundary (e.g. a
symlink/junction) -- that exclusion is reported via `warnings` instead,
not silently either.
"""

from adrpy.core.args import parse_flags
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.consistency import check_repository
from adrpy.core.errors import FailureCodes, build_failure_codes
from adrpy.core.header import has_header_shape, parse_header
from adrpy.core.lifecycle import read_header_lines_with_report, resolve_target_and_config
from adrpy.core.naming import parse_any_filename
from adrpy.core.fs import scan_tree
from adrpy.core.security import resolve_within
from adrpy.core.warnings import excluded_candidate_warning


def describe():
    return {
        "name": "explore",
        "summary": "Lists every decision file in the repository, on a best-effort basis.",
        "description": (
            "Lists every decision file in the repository, recognized or not, on a best-effort basis: "
            "a file excluded for escaping the repository boundary, a subdirectory that could not be "
            "scanned, or a single file that could not be read are all reported via `warnings` instead "
            "of silently missing from `decisions` or failing the whole command. Each entry's "
            "`header.state` is `valid`, `adulterated` (it looks like this tool's header -- a `|Adr-Plus ` row, an "
            "exact `|--|--|` line or a NUL byte within the first 12 lines -- but it does not parse) or "
            "`no-header`, with `header.invalid_reason` naming the parse failure for the last two -- a file "
            "that is not `valid` has no status the other commands can read, so they leave it out of every "
            "family rule (see doc/lifecycle.md). "
            "May fail with target-directory-not-found if --path does not point to an existing directory, "
            "or config-not-found if that directory has no adr-config.adrplus -- these two are hard "
            "failures, not part of the best-effort reporting above, since there is no repository to scan "
            "at all yet."
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
    target, config_path, config = resolve_target_and_config(path)
    folder = resolve_within(target, config.folderadr)

    entries = []
    excluded = []
    unreadable_files = []
    unreadable = []
    if folder.is_dir():
        scan = scan_tree(folder)
        excluded = list(scan.excluded)
        # scan_tree reports a subdirectory it could not list instead of
        # skipping it silently.
        unreadable = list(scan.unreadable)
        for candidate in scan.markdown:
            # Best-effort: a single persistently unreadable file (locked by
            # an editor, backup tool, or antivirus -- ordinary in a folder
            # of Markdown files people also open by hand) is reported here
            # rather than killing this entire inventory, matching the
            # unreadable-subdirectory handling just below.
            try:
                entries.append(_build_entry(candidate, config))
            except OSError:
                unreadable_files.append(candidate)

    entries.sort(
        key=lambda entry: (
            -int(entry["header"]["is_valid"]),
            int(entry["header"]["is_migrated"]),
            -entry["number"],
            -entry["version"],
            -(entry["revision"] or 0),
        )
    )

    # Every mutating command's result carries "warnings" unconditionally,
    # even when empty (see config's own read-mode) -- explore never
    # generates one from a write (it's read-only), but omitting the key
    # entirely breaks a generic wrapper that assumes `data["warnings"]`
    # always exists across all commands. is_within's own exclusion is
    # reported here too, since explore's own docstring promises no file is
    # ever dropped silently from this report.
    warnings = []
    warning = excluded_candidate_warning(excluded)
    if warning:
        warnings.append(warning)
    if unreadable:
        names = ", ".join(unreadable)
        warnings.append(
            f"{len(unreadable)} subdirectory/subdirectories under {folder} could not be scanned "
            f"(permission denied or similar) -- this report may be missing decision files inside them: {names}."
        )
    if unreadable_files:
        names = ", ".join(path.name for path in unreadable_files)
        warnings.append(
            f"{len(unreadable_files)} file(s) could not be read (permission denied or similar) and are "
            f"missing from this report: {names}."
        )
    # The repository's consistency errors (core/consistency.py), listed
    # without failing: explore stays an inventory.
    errors = check_repository(folder, config)[1]
    return {"decisions": entries, "consistency": {"errors": errors}, "warnings": warnings}


def _build_entry(path, config):
    found = parse_any_filename(path.name, config)
    scheme, parsed = found if found else (None, None)

    # Reading and decoding the file's ENTIRE content (path.read_bytes())
    # would be wasteful -- parse_header only ever consumes the first 12
    # lines, and for a large or hostile file (explore is the natural
    # "safe first look" an agent runs against an unfamiliar repository,
    # with no size warning), that's an unbounded memory read for zero
    # benefit. Confirmed live: an 800MB
    # matching file drove peak traced memory to ~2.5GB for this single
    # candidate. Uses the same bounded header read every other bulk scan
    # in this codebase already relies on (family_members, migrate's scan
    # phase) -- same PermissionError-retry tolerance, same lossy-decode
    # detection, just never loading the body.
    header_lines, encoding_repaired = read_header_lines_with_report(path)
    header = parse_header(header_lines, config)

    return {
        "filename": path.name,
        "path": str(path),
        "scheme": scheme,
        "number": parsed.number if parsed else 0,
        "version": parsed.version if parsed else 0,
        "revision": parsed.revision if parsed else None,
        "title": parsed.title if parsed else None,
        "header": {
            "is_valid": header.is_valid,
            # Only a header that parses gives a status; an invalid file is
            # left out of every family rule (see doc/lifecycle.md).
            # "adulterated": this tool's header, damaged; "no-header": none.
            "state": "valid" if header.is_valid else ("adulterated" if has_header_shape(header_lines) else "no-header"),
            "invalid_reason": None if header.is_valid else header.error,
            "is_migrated": header.is_migrated,
            "scope": header.scope,
            "domain": header.domain,
            "status_create": header.status_create,
            "date_create": header.date_create.isoformat() if header.date_create else None,
            "status_update": header.status_update,
            "date_update": header.date_update.isoformat() if header.date_update else None,
            "status_change": header.status_change,
            "date_change": header.date_change.isoformat() if header.date_change else None,
            "superseded_by_file": header.superseded_by_file,
            # Tells the caller this specific file's bytes were
            # lossy-decoded -- explore is a read-only report, the natural
            # place for this visibility.
            "encoding_repaired": encoding_repaired,
            # ADR004V01: names which status field(s), if any, had a
            # marker/label disagreement -- explore lists every decision,
            # not just the one a write command happens to be acting on,
            # so this is per-file data here rather than a warning.
            "marker_label_mismatches": list(header.marker_label_mismatches),
        },
    }
