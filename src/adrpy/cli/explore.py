"""`explore` command: read-only inventory of every decision file.
Recognizes BOTH naming schemes via `parse_any_filename` -- a file
matching neither (or one the phase rule of core/consistency.decision_names
leaves out) still appears in the report, never dropped silently. A
distinct mechanism, is_within (core/security.py), CAN still exclude a
candidate whose real path escapes the repository boundary (e.g. a
symlink/junction) -- that exclusion is reported via `warnings` instead,
not silently either.
"""

from dataclasses import asdict

from adrpy.core.args import parse_flags
from adrpy.core.config import (
    SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES,
    parse_repo_config,
    reject_overlapping_migration_pattern,
    serialize_repo_config,
)
from adrpy.core.consistency import check_repository, unheadered_legacy_warning, unrecognized_decision_like_warning
from adrpy.core.decision_log import unrecognized_log_files_warning
from adrpy.core.errors import FailureCodes, build_failure_codes
from adrpy.core.header import has_header_shape, parse_header, read_header_lines_with_report
from adrpy.core.lifecycle import (
    PATTERN_ADVICE_BEFORE_MIGRATE,
    legacy_pattern_preview,
    legacy_pattern_warnings,
    resolve_target_and_config,
)
from adrpy.core.naming import parse_any_filename
from adrpy.core.fs import scan_tree
from adrpy.core.security import resolve_within
from adrpy.core.warnings import excluded_candidate_warning


def describe():
    return {
        "name": "explore",
        "summary": "Lists every decision file in the repository, on a best-effort basis.",
        "description": (
            "Lists every file under the decisions folder, recognized or not, and never refuses an "
            "inconsistent repository: it is the inventory, so what it could not read goes to `warnings` and "
            "every rule `adrpy check` would report as broken goes to `consistency.errors`. Each entry's "
            "`header.state` is `valid`, `adulterated` (it looks like this tool's header but does not parse) "
            "or `no-header`, with `header.invalid_reason` naming the parse failure for the last two. A file whose "
            "name only migrationpattern matches and that has no header is listed with `scheme` null (not a "
            "decision) once the repository has a decision with a valid header migrate did not write, and named in "
            "`warnings` with the number read from its name. A file in the decision-log folder (folderlog) that is "
            "not a decision-log entry (INDEX.md and CYCLES.md are the log's own) is named in `warnings` too: "
            "`adrpy log` refuses to write while it is there. With "
            "--migrationpattern, the result also has `migrationpattern_preview` -- the list `adrpy config "
            "--migrationpattern` would return for that pattern (file, number, version, title of each file it "
            "recognizes), its likely-misreading warnings in `warnings` -- while writing nothing: the inventory "
            "and consistency.errors still read the repository's own config."
        ),
        "arguments": [
            {
                "name": "path",
                "alias": "-p",
                "type": "string",
                "required": True,
                "description": "Repository root directory (must contain adr-config.adrplus).",
            },
            {
                "name": "migrationpattern",
                "type": "string",
                "required": False,
                "description": (
                    "A migrationpattern to preview (same syntax as `adrpy config --migrationpattern`), read "
                    "instead of the repository's own for `migrationpattern_preview` only; nothing is written. "
                    "An invalid one fails with config-migrationpattern-invalid, as does one that reads part of a "
                    "name twice (its T starts inside its N/V/R/P range, or two of those ranges overlap; the "
                    "detail names the overlap); an empty value is a usage error (there is nothing to preview)."
                ),
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
    flags = parse_flags(args, required=("path",), optional=("migrationpattern",), aliases={"p": "path"})
    target, config_path, config = resolve_target_and_config(flags["path"])
    folder = resolve_within(target, config.folderadr)
    preview_config = None
    if "migrationpattern" in flags:
        # Validated as config would validate it (same failure code).
        preview_config = parse_repo_config(
            serialize_repo_config({**asdict(config), "migrationpattern": flags["migrationpattern"]})
        )
        reject_overlapping_migration_pattern(preview_config.migrationpattern)

    entries = []
    excluded = []
    unreadable_files = []
    unreadable = []
    # One traversal and one read per file: the consistency check's own
    # snapshot (core/consistency) gives both the inventory and
    # consistency.errors.
    scan = scan_tree(folder) if folder.is_dir() else None
    snapshot, errors = check_repository(folder, config, scan)
    if scan is not None:
        excluded = list(scan.excluded)
        # scan_tree reports a subdirectory it could not list instead of
        # skipping it silently.
        unreadable = list(scan.unreadable)
        decisions = {decision.path: decision for decision in snapshot.decisions}
        # A decision file whose read failed (after the read retries) is
        # one of the check's scan-incomplete errors.
        failed = {error["file"] for error in errors if error["code"] == FailureCodes.SCAN_INCOMPLETE}
        no_header = {error["file"] for error in errors if error["code"] == FailureCodes.NO_HEADER}
        not_decisions = set(snapshot.unheadered_legacy)
        for candidate in scan.markdown:
            # Best-effort: a single persistently unreadable file (locked by
            # an editor, backup tool, or antivirus -- ordinary in a folder
            # of Markdown files people also open by hand) is reported here
            # rather than killing this entire inventory, matching the
            # unreadable-subdirectory handling just below.
            decision = decisions.get(candidate)
            if decision is not None and decision.header is not None:
                header_state = (
                    "valid"
                    if decision.header.is_valid
                    else ("no-header" if str(candidate) in no_header else "adulterated")
                )
                entries.append(
                    _entry(candidate, decision.scheme, decision.name, decision.header, header_state, decision.encoding_repaired)
                )
                continue
            if str(candidate) in failed:
                unreadable_files.append(candidate)
                continue
            # Not a decision (its name matches no scheme, or the phase
            # rule leaves it out), or one whose header lines hold
            # merge-conflict markers: read here.
            try:
                entries.append(_build_entry(candidate, config, candidate in not_decisions))
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
    for warning in (
        unrecognized_decision_like_warning(scan, config),
        unheadered_legacy_warning(snapshot, config),
        unrecognized_log_files_warning(target, config),
    ):
        if warning:
            warnings.append(warning)
    preview = None
    if preview_config is not None:
        preview = legacy_pattern_preview(scan.markdown if scan is not None else (), preview_config)
        warnings.extend(legacy_pattern_warnings(preview, PATTERN_ADVICE_BEFORE_MIGRATE))
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
    result = {"decisions": entries, "consistency": {"errors": errors}, "warnings": warnings}
    if preview is not None:
        result["migrationpattern_preview"] = preview
    return result


def _build_entry(path, config, not_a_decision=False):
    found = None if not_a_decision else parse_any_filename(path.name, config)
    scheme, parsed = found if found else (None, None)

    # Reading and decoding the file's ENTIRE content (path.read_bytes())
    # would be wasteful -- parse_header only ever consumes the first 12
    # lines, and for a large or hostile file (explore is the natural
    # "safe first look" an agent runs against an unfamiliar repository,
    # with no size warning), that's an unbounded memory read for zero
    # benefit (an 800MB matching file once drove peak memory to ~2.5GB
    # for this single candidate). Uses the same bounded header read as
    # the repository scan (core/consistency) and migrate's scan -- same
    # PermissionError-retry tolerance, same lossy-decode detection, just
    # never loading the body.
    header_lines, encoding_repaired = read_header_lines_with_report(path)
    header = parse_header(header_lines, config)
    # "adulterated": this tool's header, damaged; "no-header": none.
    header_state = "valid" if header.is_valid else ("adulterated" if has_header_shape(header_lines) else "no-header")
    return _entry(path, scheme, parsed, header, header_state, encoding_repaired)


def _entry(path, scheme, parsed, header, header_state, encoding_repaired):
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
            # Only a header that parses gives a status; a file with an ADR
            # name that is not `valid` is also one of consistency.errors.
            "state": header_state,
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
