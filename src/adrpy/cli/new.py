"""`new` command: creates a new decision with status Proposed. `--open`
(would launch an external editor via an app-level setting) is permanently
not implemented --
a deliberate divergence, not a gap to fill later: adrpy-ai is
args-in/JSON-out for a non-interactive caller, with no session to hand
an opened editor back to (decision-log:
accepted-divergence--2026-09-15--cli--open-flag-not-implemented.md).
"""

from adrpy.core.args import parse_flags
from adrpy.core.atomic_write import atomic_write_text, cleanup_orphaned_temp_files
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.lifecycle import (
    find_by_unique_title,
    next_number,
    parse_refdate,
    resolve_target_and_config,
    scan_decisions,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.naming import build_filename
from adrpy.core.security import reject_embedded_delimiter, resolve_within
from adrpy.core.warnings import attach_warnings, orphan_cleanup_warning, retry_warning


def describe():
    return {
        "name": "new",
        "summary": "Creates a new decision, status Proposed.",
        "description": (
            "Creates a new decision with status Proposed. "
            "May fail with repository-locked if the repository lock could not be acquired in time, or "
            "lock-lost if it was acquired but reclaimed by another process before the write could commit -- "
            "in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write was "
            "made either way; retry. May also fail with new-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- title-uniqueness and "
            "next-number allocation can't be trusted from an incomplete scan; no write was made."
        ),
        "arguments": [
            {"name": "path", "alias": "-p", "type": "string", "required": True, "description": "Repository root directory."},
            {
                "name": "title",
                "alias": "-t",
                "type": "string",
                "required": True,
                "description": (
                    "Title of the new decision. Cannot contain '|' or a line-break-like character "
                    "(field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "domain",
                "alias": "-d",
                "type": "string",
                "required": False,
                "description": (
                    "Optional domain header field. Cannot contain '|' or a line-break-like character "
                    "(field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    "Optional scope header field. Cannot contain '|' or a line-break-like character "
                    "(field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "refdate",
                "alias": "-r",
                "type": "string",
                "required": False,
                "description": (
                    "Reference date (YYYY-MM-DD); defaults to today. Must not be in the future -- a brand "
                    "new decision has no prior history to be before (refdate-invalid-format/"
                    "refdate-in-future)."
                ),
            },
        ],
    }


def run(args):
    flags = parse_flags(
        args,
        required=("path", "title"),
        optional=("domain", "scope", "refdate"),
        aliases={"p": "path", "t": "title", "d": "domain", "s": "scope", "r": "refdate"},
    )
    title = flags["title"]
    domain = flags.get("domain", "")
    scope = flags.get("scope", "")

    target, config_path, config = resolve_target_and_config(flags["path"])

    reject_embedded_delimiter(title, "title")
    reject_embedded_delimiter(domain, "domain")
    reject_embedded_delimiter(scope, "scope")

    refdate = parse_refdate(flags.get("refdate"))
    validate_refdate_not_in_future(refdate)

    folder = resolve_within(target, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # The whole scan -> decide-next-number -> write sequence is the
        # critical section -- two calls that both scan before either writes
        # will otherwise compute the identical "next" number (reproduced
        # live, 10/10 times, with two concurrent `new` calls).
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # `folder` above was resolved from a config read BEFORE this
            # lock -- a concurrent config change could have moved
            # folderadr in the window before the lock was actually
            # acquired, in which case `folder` (and so this lock) no
            # longer names the repository's real decisions folder.
            # Re-reads fresh and aborts rather than scanning/writing
            # against a directory nobody uses anymore.
            config = verify_folderadr_unchanged_since_lock(config_path, config.folderadr, warnings=warnings)
            # strict=True: this scan feeds both title-uniqueness
            # (find_by_unique_title, below) and next-number allocation,
            # both real safety decisions. An unreadable subdirectory hiding
            # an existing title or a higher number must never be silently
            # treated as "not found" the way explore's own best-effort
            # listing can.
            decisions = scan_decisions(
                folder, config, warnings=warnings, strict=True, incomplete_code="new-scan-incomplete"
            )

            existing = find_by_unique_title(title, config, decisions)
            if existing is not None:
                raise CommandError(
                    "title-already-exists",
                    f"A decision with this title already exists: {existing.name}",
                    data={"existing_file": existing.name},
                    warnings=warnings,
                )

            record = DecisionRecord(
                number=next_number(decisions),
                title=title,
                version=1,
                revision=1 if config.lenrevision > 0 else None,
                scope=scope,
                domain=domain,
                status_create="Proposed",
                date_create=refdate,
            )

            filename = build_filename(config, record)
            file_path = resolve_within(folder, filename)
            if file_path.exists():
                raise CommandError(
                    "file-already-exists",
                    f"File already exists: {filename}",
                    data={"file": filename},
                    warnings=warnings,
                )

            content = build_header(config, record) + config.template
            # ADR001, part 3 (doc/adr/ADR001V01-...): guarantees this write
            # never commits blindly if the lease was reclaimed.
            lock.verify_still_held()
            attempts = atomic_write_text(file_path, content)
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # The canonical keyword, not the repo's configured label -- `explore`
    # reports status_create the same way for the same file, and the two
    # must agree even when statusnew is customized.
    return {"created": str(file_path), "status": "Proposed", "warnings": warnings}
