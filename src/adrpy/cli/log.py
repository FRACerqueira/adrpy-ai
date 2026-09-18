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

from pathlib import Path

from adrpy.core.args import parse_flags
from adrpy.core.config import load_repo_config
from adrpy.core.decision_log import (
    CLASSIFICATIONS,
    DEFERRED_CLASSIFICATION,
    STRUCTURED_CLASSIFICATIONS,
    build_entry_content,
    build_filename,
    decision_log_dir_for,
    next_round,
    regenerate_index,
    validate_classification,
    validate_slug,
)
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.lifecycle import parse_refdate, validate_refdate_not_in_future, verify_folderadr_unchanged_since_lock
from adrpy.core.lock import LockLostError, acquire_repo_lock
from adrpy.core.security import reject_embedded_delimiter, resolve_within
from adrpy.core.warnings import attach_warnings, retry_warning

_STRUCTURED_FIELDS = ("front", "severity", "resolution")


def describe():
    return {
        "name": "log",
        "description": (
            "Writes a decision-log entry: the lighter-weight sibling of a formal ADR, for an event worth "
            "recording that is not itself an architectural decision (see doc/decision-log-workflow.md for "
            "when to use this instead of an ADR). Owns only the mechanical part of the record -- classification, "
            "scope, slug, summary, and body are all required arguments, since this command never decides what "
            "to log, only how to write it down once that's already been decided. May fail with "
            "log-classification-invalid if --classification is not one of the closed set named on that "
            "argument below, or log-slug-invalid if --slug is not valid kebab-case. May fail with "
            "repository-locked if the repository lock could not be acquired in time, or lock-lost if it was "
            "acquired but reclaimed before the write could commit -- in both cases no write was made. May also "
            "fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr "
            "while this call was acquiring the lock -- no write was made either way; retry. May also fail with "
            "log-entry-already-exists if an entry with the same date/classification/scope/slug already exists "
            "-- no write was made; this is a signal the new entry is a likely duplicate or should be a "
            "retraction of the existing one, not an accident to silently rename around. May also fail with "
            "log-index-regeneration-failed if the entry itself was written successfully but regenerating "
            "INDEX.md failed afterward (e.g. a permission error) -- `data.file` names the entry that was "
            "already committed to disk despite the overall failure."
        ),
        "arguments": [
            {"name": "path", "alias": "-p", "type": "string", "required": True, "description": "Repository root directory."},
            {
                "name": "classification",
                "alias": "-c",
                "type": "string",
                "required": True,
                "description": f"One of: {', '.join(CLASSIFICATIONS)}.",
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": True,
                "description": (
                    "The module/command/concern this entry is about, reusing the project's own vocabulary. "
                    "Cannot contain '|' or a line-break-like character (field-contains-forbidden-character)."
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
                    "line-break-like character (field-contains-forbidden-character)."
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
                    "audit-finding or doc-drift; usage-error otherwise. Which review angle found this."
                ),
            },
            {
                "name": "severity",
                "type": "string",
                "required": False,
                "description": "One of: Low, Medium, High. Required together with --front/--resolution for audit-finding/doc-drift.",
            },
            {
                "name": "resolution",
                "type": "string",
                "required": False,
                "description": (
                    "One of: Direct, Escalated, Retraction. Required together with --front/--severity for "
                    "audit-finding/doc-drift. --round is never a flag -- this command computes it "
                    "automatically (highest existing Round across audit-finding/doc-drift entries, plus one), "
                    "the same class of allocation as an ADR's own next_number, so it can never be typed wrong "
                    "or reused by mistake."
                ),
            },
            {
                "name": "reopenwhen",
                "type": "string",
                "required": False,
                "description": (
                    "Required, and only valid, when --classification is deferred; usage-error otherwise. The "
                    "concrete, checkable condition that reopens this deferred item."
                ),
            },
        ],
    }


def run(args):
    flags = parse_flags(
        args,
        required=("path", "classification", "scope", "slug", "summary", "body"),
        optional=("refdate",) + _STRUCTURED_FIELDS + ("reopenwhen",),
        aliases={"p": "path", "c": "classification", "s": "scope", "r": "refdate"},
    )
    target = Path(flags["path"])
    classification = flags["classification"]
    scope = flags["scope"]
    slug = flags["slug"]
    summary = flags["summary"]
    body = flags["body"]

    validate_classification(classification)
    validate_slug(slug)
    reject_embedded_delimiter(scope, "scope")
    reject_embedded_delimiter(summary, "summary")

    provided_structured = [name for name in _STRUCTURED_FIELDS if name in flags]
    provided_reopenwhen = "reopenwhen" in flags

    if classification in STRUCTURED_CLASSIFICATIONS:
        missing = [name for name in _STRUCTURED_FIELDS if name not in flags]
        if missing:
            raise UsageError(
                f"--{'/--'.join(missing)} required when --classification is '{classification}'."
            )
        if provided_reopenwhen:
            raise UsageError(f"--reopenwhen is not valid when --classification is '{classification}'.")
    elif classification == DEFERRED_CLASSIFICATION:
        if not provided_reopenwhen:
            raise UsageError("--reopenwhen required when --classification is 'deferred'.")
        if provided_structured:
            raise UsageError(
                f"--{'/--'.join(provided_structured)} not valid when --classification is 'deferred' "
                "(only --reopenwhen applies)."
            )
    elif provided_structured or provided_reopenwhen:
        offending = provided_structured + (["reopenwhen"] if provided_reopenwhen else [])
        raise UsageError(
            f"--{'/--'.join(offending)} only valid when --classification is audit-finding/doc-drift "
            f"(--front/--severity/--resolution) or deferred (--reopenwhen), not '{classification}'."
        )

    if not target.is_dir():
        raise CommandError("target-directory-not-found", f"Directory does not exist: {flags['path']}")

    config_path = target / "adr-config.adrplus"
    if not config_path.is_file():
        raise CommandError("config-not-found", f"No adr-config.adrplus found at: {config_path}")
    config = load_repo_config(config_path)

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
            log_dir = decision_log_dir_for(folder)

            round_ = next_round(log_dir) if classification in STRUCTURED_CLASSIFICATIONS else None

            filename = build_filename(refdate, classification, scope, slug)
            file_path = log_dir / filename
            if file_path.exists():
                raise CommandError(
                    "log-entry-already-exists",
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
                regenerate_index(log_dir)
            except (OSError, LockLostError) as error:
                # The entry above is already committed to disk for real --
                # `data.file` names that partial success explicitly, the
                # same shape reject/supersede already use for their own
                # second-write failures.
                raise CommandError(
                    "log-index-regeneration-failed",
                    f"{file_path}: entry written, but regenerating INDEX.md failed: {error}",
                    data={"file": str(file_path)},
                    warnings=warnings,
                ) from error

    return {"created": str(file_path), "round": round_, "warnings": warnings}
