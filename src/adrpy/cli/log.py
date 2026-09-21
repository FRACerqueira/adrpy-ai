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
from adrpy.core.errors import CommandError, FailureCodes, UsageError
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.lifecycle import (
    parse_refdate,
    resolve_target_and_config,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import LockLostError, acquire_repo_lock
from adrpy.core.security import reject_aliased_repo_folders, reject_embedded_delimiter, resolve_within
from adrpy.core.warnings import attach_warnings, retry_warning

_STRUCTURED_FIELDS = ("front", "severity", "resolution")


def describe():
    return {
        "name": "log",
        "summary": "Writes a decision-log entry -- the lighter-weight sibling of a formal ADR.",
        "description": (
            "Writes a decision-log entry: the lighter-weight sibling of a formal ADR, for an event worth "
            "recording that is not itself an architectural decision (see doc/decision-log-workflow.md for "
            "when to use this instead of an ADR). Owns only the mechanical part of the record -- classification, "
            "scope, slug, summary, and body are all required arguments, since this command never decides what "
            "to log, only how to write it down once that's already been decided. Result shape: {\"created\": "
            "<path written>, \"round\": <int for audit-finding/doc-drift, else null>, \"warnings\": [...]}. May "
            "also fail with target-directory-not-found if --path does not point to an existing directory, "
            "or config-not-found if that directory has no adr-config.adrplus -- no write is attempted "
            "either way. May "
            "fail with log-classification-invalid if --classification is not one of the closed set named on "
            "that argument below, log-slug-invalid if --slug is not valid kebab-case, or log-scope-invalid if "
            "--scope is not valid kebab-case (scope becomes a literal segment of the entry's own filename, so "
            "'/', '\\\\', and an embedded '--' are rejected, not just cosmetically discouraged). May fail with "
            "repository-locked if the repository lock could not be acquired in time, or lock-lost if it was "
            "acquired but reclaimed before the write could commit -- in both cases no write was made. May also "
            "fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr "
            "while this call was acquiring the lock -- no write was made either way; retry. May also fail with "
            "log-entry-already-exists (data.file: the bare filename) if an entry with the same "
            "date/classification/scope/slug already exists -- no write was made; this is a signal the new "
            "entry is a likely duplicate or should be a retraction of the existing one, not an accident to "
            "silently rename around. An existing file in the decision-log directory that doesn't match the "
            "expected naming shape refuses to be guessed past, but WHEN this surfaces depends on "
            "--classification: for audit-finding/doc-drift, the directory is scanned for Round allocation "
            "before any write, so this fails cleanly as log-directory-contains-unrecognized-file with nothing "
            "written; for every other classification, the directory is only scanned during index regeneration, "
            "AFTER the entry write already committed, so this surfaces as log-index-regeneration-failed instead "
            "(same as any other index-regeneration failure, e.g. a permission error) -- data.file (the full "
            "path, unlike log-entry-already-exists' bare filename above) names the entry that was already "
            "committed to disk despite the overall failure; the offending file's own name is in the detail text. "
            "The decision-log directory (config.folderlog, ADR007V01) is scanned recursively -- an unreadable "
            "subdirectory under it fails closed the same way, as log-scan-incomplete (before any write, or "
            "wrapped into log-index-regeneration-failed after, following the exact same before/after split as "
            "log-directory-contains-unrecognized-file above)."
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
                    "requires --reopenwhen; every other value accepts none of those four flags (usage-error "
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

    target, config_path, config = resolve_target_and_config(flags["path"])

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)

    folder = resolve_within(target, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        # ADR001's coverage requirement (doc/adr/ADR001V01-...): reuses the
        # exact same lock every other mutating command uses (scoped to the
        # ADR decisions folder, not the decision-log folder) -- one uniform
        # mechanism, not a bespoke one for this command's own writes.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            config = verify_folderadr_unchanged_since_lock(config_path, config.folderadr, warnings=warnings)
            folder = resolve_within(target, config.folderadr)
            # Round 30: the schema-time containment guard (core/config.py's
            # own parse_repo_config) can never see a junction/symlink
            # planted inside the repo tree -- this re-checks against the
            # REAL, resolved directories, right before folderlog is
            # actually used, inside the same lock/freshness window as the
            # folderadr re-check just above.
            reject_aliased_repo_folders(target, config)
            log_dir = decision_log_dir_for(target, config)

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
            if file_path.exists():
                raise CommandError(
                    FailureCodes.LOG_ENTRY_ALREADY_EXISTS,
                    f"Decision-log entry already exists: {filename}",
                    data={"file": filename},
                    warnings=warnings,
                )

            content = build_entry_content(
                summary,
                body,
                front=flags.get("front"),
                severity=flags.get("severity"),
                resolution=flags.get("resolution"),
                round_=round_,
                reopen_when=flags.get("reopenwhen"),
            )

            lock.verify_still_held()
            # Same TOCTOU reasoning as init's own folder creation: two
            # concurrent first-ever `log` calls both want this directory to
            # exist, with no conflicting content to lose -- exist_ok=True
            # closes the race outright.
            log_dir.mkdir(parents=True, exist_ok=True)
            attempts = atomic_write_text(file_path, content)
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

            try:
                # Second write in the same critical section -- re-verified
                # for the same reason as the entry write above.
                lock.verify_still_held()
                regenerate_index(log_dir, warnings=warnings)
            except (OSError, LockLostError, CommandError) as error:
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

    return {"created": str(file_path), "round": round_, "warnings": warnings}
