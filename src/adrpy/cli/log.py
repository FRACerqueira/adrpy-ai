"""`log` command: writes a decision-log entry -- the lighter-weight
sibling of a formal ADR, for an event worth recording that is not
itself an architectural decision (ADR003V01). Owns only the mechanical
part of that record: constructing the filename, formatting the
classification-specific structured line, writing the entry, and
regenerating INDEX.md as part of the same operation. It never decides
*what* to log -- classification, scope, slug, summary, and body are all
required arguments, resolved through the review process described in
doc/decision-log-workflow.md before this command is ever called.
"""

from adrpy.core.args import parse_flags
from adrpy.core.decision_log import (
    CLASSIFICATIONS,
    DEFERRED_CLASSIFICATION,
    RESOLUTIONS,
    SEVERITIES,
    STRUCTURED_CLASSIFICATIONS,
    build_entry_content,
    build_filename,
    decision_log_dir_for,
    max_existing_round,
    parse_round,
    regenerate_index,
    validate_classification,
    validate_resolution,
    validate_round_not_regressing,
    validate_scope,
    validate_severity,
    validate_slug,
)
from adrpy.core.config import SHARED_FAILURE_CODES as CONFIG_FAILURE_CODES
from adrpy.core.output import explain
from adrpy.core.errors import CommandError, FailureCodes, UsageError, build_failure_codes
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.lifecycle import (
    parse_refdate,
    resolve_target_and_config,
    validate_refdate_not_in_future,
)
from adrpy.core.security import reject_aliased_repo_folders, reject_embedded_delimiter, resolve_within
from adrpy.core.fs import cleanup_orphaned_temp_files
from adrpy.core.warnings import attach_warnings, orphan_cleanup_warning, retry_warning

_STRUCTURED_FIELDS = ("front", "severity", "resolution")


def describe():
    return {
        "name": "log",
        "summary": "Writes a decision-log entry -- the lighter-weight sibling of a formal ADR.",
        "description": (
            "Writes a decision-log entry under folderlog -- the lighter-weight sibling of an ADR, for an "
            "event worth recording that is not an architectural decision (see https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/decision-log-workflow.md) "
            "-- and regenerates the log's INDEX.md. It owns only the mechanics: every value is an argument, "
            "checked before the write, and the result is {created, round, warnings}, `round` being allocated "
            "for audit-finding/doc-drift. An entry already written stays on disk when the index regeneration "
            "after it fails; data.file then names it."
        ),
        "arguments": [
            {"name": "path", "alias": "-p", "type": "string", "required": True, "description": "Repository root directory."},
            {
                "name": "classification",
                "alias": "-c",
                "type": "string",
                "required": True,
                "description": (
                    f"One of: {', '.join(CLASSIFICATIONS)}. audit-finding/doc-drift additionally require "
                    "--front/--severity/--resolution (and accept optional --round); deferred additionally "
                    "requires --reopenwhen; every other value accepts none of those five flags (usage-error "
                    "if any are passed)."
                ),
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": True,
                "description": (
                    "The module/command/concern this entry is about, reusing the project's own vocabulary. "
                    "Valid kebab-case only -- lowercase letters/digits, single hyphens, no '/', '\\', or "
                    "embedded '--' (log-scope-invalid); becomes a literal segment of the entry's own filename."
                ),
            },
            {
                "name": "slug",
                "type": "string",
                "required": True,
                "description": (
                    "A few kebab-case words identifying this specific entry -- lowercase letters/digits only, "
                    "single hyphens between words, no leading/trailing/double hyphens (log-slug-invalid). What "
                    "actually guarantees the filename is unique."
                ),
            },
            {
                "name": "summary",
                "type": "string",
                "required": True,
                "description": (
                    "One-line summary -- becomes the entry's own '#' heading. Cannot contain '|' or a "
                    "line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "body",
                "type": "string",
                "required": True,
                "description": "Free-form body text, written below the heading (and the structured line, if any).",
            },
            {
                "name": "refdate",
                "alias": "-r",
                "type": "string",
                "required": False,
                "description": (
                    "Reference date (YYYY-MM-DD) used as the entry's own filename date; defaults to today. Must "
                    "not be in the future (refdate-invalid-format/refdate-in-future)."
                ),
            },
            {
                "name": "front",
                "type": "string",
                "required": False,
                "description": (
                    "Required together with --severity/--resolution, only when --classification is "
                    "audit-finding or doc-drift; usage-error otherwise. Which review angle found this. Cannot "
                    "contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "severity",
                "type": "string",
                "required": False,
                "description": (
                    f"One of: {', '.join(SEVERITIES)} (log-severity-invalid otherwise). Required together with "
                    "--front/--resolution for audit-finding/doc-drift."
                ),
            },
            {
                "name": "resolution",
                "type": "string",
                "required": False,
                "description": (
                    f"One of: {', '.join(RESOLUTIONS)} (log-resolution-invalid otherwise). Required together "
                    "with --front/--severity for audit-finding/doc-drift."
                ),
            },
            {
                "name": "round",
                "type": "integer",
                "required": False,
                "description": (
                    "Only valid when --classification is audit-finding or doc-drift; usage-error otherwise. "
                    "Optional even then: omit it to auto-assign the next round (highest existing Round across "
                    "audit-finding/doc-drift entries, plus one) -- the safe default when starting a new round. "
                    "Pass it explicitly to REUSE a round already in progress (the common case: a second finding "
                    "in the same round), which auto-assignment can never do on its own. Must be a positive "
                    "integer (log-round-invalid) not lower than the highest Round already recorded "
                    "(log-round-too-low) -- Round never decreases. When omitted, the result's own `warnings` "
                    "names the round that was auto-assigned, so an accidental new-round-instead-of-reuse is "
                    "visible immediately instead of discovered later."
                ),
            },
            {
                "name": "reopenwhen",
                "type": "string",
                "required": False,
                "description": (
                    "Required, and only valid, when --classification is deferred; usage-error otherwise. The "
                    "concrete, checkable condition that reopens this deferred item. Cannot contain '|' or a "
                    "line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
        ],
        "failure_codes": build_failure_codes(
            {
                FailureCodes.TARGET_DIRECTORY_NOT_FOUND: "--path does not point to an existing directory.",
                FailureCodes.CONFIG_NOT_FOUND: "--path's own directory has no adr-config.adrplus.",
                FailureCodes.FOLDERADR_FOLDERLOG_ALIAS_SAME_DIRECTORY: "folderadr and folderlog resolve to the same real directory (or one nested inside the other), typically via a symlink or junction.",
                FailureCodes.LOG_CLASSIFICATION_INVALID: "--classification is not one of the recognized classifications.",
                FailureCodes.LOG_SLUG_INVALID: "--slug is not valid kebab-case.",
                FailureCodes.LOG_SCOPE_INVALID: "--scope is not valid kebab-case, or contains '/' or '\\'.",
                FailureCodes.LOG_SEVERITY_INVALID: "--severity is not one of Low/Medium/High.",
                FailureCodes.LOG_RESOLUTION_INVALID: "--resolution is not one of Direct/Escalated/Retraction.",
                FailureCodes.LOG_ROUND_INVALID: "--round is not a positive integer.",
                FailureCodes.REFDATE_INVALID_FORMAT: "--refdate is not an ISO 8601 date (give it as YYYY-MM-DD).",
                FailureCodes.REFDATE_IN_FUTURE: "--refdate is after today.",
                FailureCodes.LOG_ROUND_TOO_LOW: "--round is lower than the highest Round already recorded.",
                FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER: "summary/front/reopenwhen contains '|' or a line-break-like character.",
                FailureCodes.FIELD_IS_BLANK: "summary/front/reopenwhen is non-empty but blank after stripping whitespace.",
                FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE: "A file under folderlog does not match the expected filename shape, or carries an unrecognized classification, or has no content, or (checked only when this call's own --classification is audit-finding/doc-drift) is an audit-finding/doc-drift entry whose Round is missing or not a plain integer -- Round/INDEX.md can't be safely computed while it's present.",
                FailureCodes.LOG_SCAN_INCOMPLETE: "A subdirectory under folderlog could not be scanned.",
                FailureCodes.LOG_ENTRY_ALREADY_EXISTS: "An entry with this exact date/classification/scope/slug already exists -- no entry was written, but INDEX.md is regenerated so it lists the existing one (a warning says so when that regeneration itself fails).",
                FailureCodes.LOG_INDEX_REGENERATION_FAILED: "The entry itself was written, but regenerating INDEX.md afterward failed.",
                FailureCodes.INTERRUPTED: "Interrupted (Ctrl+C) after the entry was written but before INDEX.md was regenerated; data.file names the entry. An interrupt before the entry is written is reported without data.",
                FailureCodes.PATH_INVALID: "A resolved path is not usable (e.g. contains a NUL byte).",
                FailureCodes.PATH_OUTSIDE_REPOSITORY: "A resolved path escapes the repository boundary.",
                FailureCodes.IO_ERROR: "A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.).",
            },
            CONFIG_FAILURE_CODES,
        ),
    }


def run(args):
    flags = parse_flags(
        args,
        required=("path", "classification", "scope", "slug", "summary", "body"),
        optional=("refdate",) + _STRUCTURED_FIELDS + ("round", "reopenwhen"),
        aliases={"p": "path", "c": "classification", "s": "scope", "r": "refdate"},
    )
    classification = flags["classification"]
    scope = flags["scope"]
    slug = flags["slug"]
    summary = flags["summary"]
    body = flags["body"]

    validate_classification(classification)
    validate_scope(scope)
    validate_slug(slug)
    reject_embedded_delimiter(summary, "summary")

    provided_structured = [name for name in _STRUCTURED_FIELDS if name in flags]
    provided_round = "round" in flags
    provided_reopenwhen = "reopenwhen" in flags

    if classification in STRUCTURED_CLASSIFICATIONS:
        missing = [name for name in _STRUCTURED_FIELDS if name not in flags]
        if missing:
            raise UsageError(
                f"--{'/--'.join(missing)} required when --classification is '{classification}'."
            )
        if provided_reopenwhen:
            raise UsageError(f"--reopenwhen is not valid when --classification is '{classification}'.")
        validate_severity(flags["severity"])
        validate_resolution(flags["resolution"])
        # front is the only one of the three still free text -- severity/
        # resolution are already constrained to a closed set above, which
        # can never contain a delimiter, so checking them here would be
        # dead code.
        reject_embedded_delimiter(flags["front"], "front")
        explicit_round = parse_round(flags["round"]) if provided_round else None
    elif classification == DEFERRED_CLASSIFICATION:
        if not provided_reopenwhen:
            raise UsageError("--reopenwhen required when --classification is 'deferred'.")
        if provided_structured:
            raise UsageError(
                f"--{'/--'.join(provided_structured)} not valid when --classification is 'deferred' "
                "(only --reopenwhen applies)."
            )
        if provided_round:
            raise UsageError("--round is not valid when --classification is 'deferred'.")
        reject_embedded_delimiter(flags["reopenwhen"], "reopenwhen")
        explicit_round = None
    else:
        offending = provided_structured + (["round"] if provided_round else []) + (
            ["reopenwhen"] if provided_reopenwhen else []
        )
        if offending:
            raise UsageError(
                f"--{'/--'.join(offending)} only valid when --classification is audit-finding/doc-drift "
                f"(--front/--severity/--resolution/--round) or deferred (--reopenwhen), not '{classification}'."
            )
        explicit_round = None

    target, _config_path, config = resolve_target_and_config(flags["path"])

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)

    warnings = []
    with attach_warnings(warnings):
        # The schema-time containment guard (core/config.py's
        # own parse_repo_config) can never see a junction/symlink
        # planted inside the repo tree -- this re-checks against the
        # REAL, resolved directories, right before folderlog is
        # actually used.
        reject_aliased_repo_folders(target, config)
        log_dir = decision_log_dir_for(target, config)
        # folderlog is this tool's own folder: every temp an interrupted
        # write left there (INDEX.md's, an entry's) is swept, as in folderadr.
        if log_dir.is_dir():
            warning = orphan_cleanup_warning(
                cleanup_orphaned_temp_files(log_dir, warnings=warnings), relative_to=log_dir
            )
            if warning:
                warnings.append(warning)

        round_ = None
        if classification in STRUCTURED_CLASSIFICATIONS:
            current_max = max_existing_round(log_dir, warnings=warnings)
            if explicit_round is not None:
                validate_round_not_regressing(explicit_round, current_max)
                round_ = explicit_round
            else:
                round_ = current_max + 1
                if current_max:
                    warnings.append(
                        f"Round {round_} was auto-assigned (no --round given). If this entry should "
                        f"share the round already in progress, retry with --round {current_max} explicitly."
                    )
                else:
                    warnings.append(
                        f"Round {round_} was auto-assigned (no --round given, and no prior round exists "
                        "yet)."
                    )

        filename = build_filename(refdate, classification, scope, slug)
        # Second, independent layer of defense beyond validate_scope's
        # own kebab-case check: a future weakening of that regex, e.g.
        # reusing reject_embedded_delimiter instead, must not silently
        # let scope escape log_dir -- the same real-path-resolution
        # guard new.py's own file_path already goes through, not just
        # a stricter regex.
        file_path = resolve_within(log_dir, filename)

        content = build_entry_content(
            summary,
            body,
            front=flags.get("front"),
            severity=flags.get("severity"),
            resolution=flags.get("resolution"),
            round_=round_,
            reopen_when=flags.get("reopenwhen"),
        )

        # Same TOCTOU reasoning as init's own folder creation: two
        # concurrent first-ever `log` calls both want this directory to
        # exist, with no conflicting content to lose -- exist_ok=True
        # closes the race outright.
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            attempts = atomic_write_text(file_path, content, exclusive=True)
        except FileExistsError as error:
            # An identical retry after log-index-regeneration-failed
            # lands here forever; rebuilding INDEX.md (a full,
            # idempotent regeneration from the entries on disk) lets
            # that retry still converge. Best-effort: the refusal below
            # is the answer either way.
            try:
                regenerate_index(log_dir, warnings=warnings)
            except (OSError, CommandError) as index_error:
                warnings.append(
                    f"INDEX.md could not be regenerated ({explain(index_error)}); it may not list every "
                    "entry, and will catch up on the next log call that succeeds."
                )
            raise CommandError(
                FailureCodes.LOG_ENTRY_ALREADY_EXISTS,
                f"Decision-log entry already exists: {filename}",
                data={"file": filename},
                warnings=warnings,
            ) from error
        warning = retry_warning(attempts)
        if warning:
            warnings.append(warning)

        try:
            regenerate_index(log_dir, warnings=warnings)
        except (OSError, CommandError) as error:
            # The entry above is already committed to disk for real --
            # `data.file` names that partial success explicitly, the
            # same shape reject/supersede already use for their own
            # second-write failures. CommandError here is either
            # log-directory-contains-unrecognized-file or (ADR007V01,
            # folderlog now recursively scanned) log-scan-incomplete
            # -- both are the only ones regenerate_index itself can
            # raise, and each one's own detail text already names the
            # offending file/subdirectory, so it isn't duplicated into
            # `data` alongside the entry's own path.
            raise CommandError(
                FailureCodes.LOG_INDEX_REGENERATION_FAILED,
                f"{file_path}: entry written, but regenerating INDEX.md failed: {error}",
                data={"file": str(file_path)},
                warnings=warnings,
            ) from error
        except BaseException as error:
            # Ctrl+C (or anything unexpected) here: the entry is on disk
            # all the same, so the answer names it too.
            raise CommandError(
                FailureCodes.INTERRUPTED,
                f"{file_path}: entry written, but interrupted ({explain(error)}) before INDEX.md was regenerated; "
                "the next log call that succeeds regenerates it.",
                data={"file": str(file_path)},
                warnings=warnings,
            ) from error

    return {"created": str(file_path), "round": round_, "warnings": warnings}
