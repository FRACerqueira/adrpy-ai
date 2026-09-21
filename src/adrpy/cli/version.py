"""`version` command: creates a new major version of an Accepted/Rejected
decision. `--open` is permanently not implemented (see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text, cleanup_orphaned_temp_files
from adrpy.core.lifecycle import (
    family_members,
    has_pending_sibling,
    has_superseded_sibling,
    ineligibility_reason_for_version_or_revise,
    latest_in_family,
    parse_refdate,
    read_body,
    read_target,
    resolve_repo_and_target,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.naming import build_filename
from adrpy.core.security import (
    reject_embedded_delimiter,
    reject_filesystem_unsafe_title,
    reject_title_with_no_case_transform_content,
    resolve_within,
)
from adrpy.core.warnings import attach_warnings, encoding_repaired_source_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "still-proposed": "This decision must be Accepted or Rejected before a new version can be created.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
    "unexpected-status": "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "version",
        "summary": "Creates a new major version of an Accepted/Rejected decision.",
        "description": (
            "Creates a new major version of an Accepted/Rejected decision. "
            "May fail with repository-locked if the repository lock could not be acquired in time, or "
            "lock-lost if it was acquired but reclaimed by another process before the write could commit -- "
            "in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a "
            "concurrent config change moved folderadr while this call was acquiring the lock -- no write was "
            "made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the "
            "decisions folder could not be scanned (permission denied or similar) -- family membership "
            "can't be trusted from an incomplete scan; no write was made. May also fail with "
            "family-scan-unreliable-encoding (data.unreliable_files names the affected file(s)) if a sibling "
            "needed a lossy UTF-8 decode -- its parsed header can't be trusted for a safety decision either, "
            "the same reasoning as an unreadable subdirectory; no write was made. The target's own title (re-read "
            "from its header cell, not a flag) is re-validated before use -- may fail with "
            "field-contains-forbidden-character if a hand-edited or migrated source file's title carries "
            "'|', a line-break-like character, a filesystem-unsafe character (`<>:\"/\\|?*` or a control "
            "character; title lands inside an actual filename component, not just a header-table cell), or "
            "consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls "
            "back to echoing such a value raw, which can collide with the filename's own separator and "
            "produce a successor file the tool can never recognize again."
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
                "name": "domain",
                "alias": "-d",
                "type": "string",
                "required": False,
                "description": (
                    "Domain for the new version; defaults to the latest version's own value. Cannot contain "
                    "'|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "scope",
                "alias": "-s",
                "type": "string",
                "required": False,
                "description": (
                    "Scope for the new version; defaults to the latest version's own value. Cannot contain "
                    "'|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank)."
                ),
            },
            {
                "name": "refdate",
                "alias": "-r",
                "type": "string",
                "required": False,
                "description": (
                    "Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before "
                    "the LATEST family member's own last update date (or creation date, if never updated) "
                    "-- not necessarily this file's own date, when branching off an older Rejected sibling "
                    "(refdate-invalid-format/refdate-in-future/refdate-before-history)."
                ),
            },
            {
                "name": "empty",
                "alias": "-e",
                "type": "switch",
                "required": False,
                # Presence-only (`--empty` with no value, like a getopt
                # flag), not "boolean" -- `--empty true`/`--empty false`
                # both fail with "Unknown argument", unlike
                # `config --disableplugins`, which does take a value.
                "description": (
                    "Start from the default template instead of carrying the source's content forward. "
                    "Presence-only: pass just '--empty' with no value; do not pass '--empty true/false'."
                ),
            },
        ],
    }


def run(args):
    flags = parse_flags(
        args,
        required=("file",),
        optional=("domain", "scope", "refdate"),
        switches=("empty",),
        aliases={"f": "file", "d": "domain", "s": "scope", "r": "refdate", "e": "empty"},
    )
    config, root, path = resolve_repo_and_target(flags["file"])
    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # The family-state read (latest/sibling checks) and the eventual
        # write must be one critical section -- a concurrent
        # supersede/approve/etc. on a sibling could otherwise slip in
        # between, and this call's next-version-number decision could go
        # stale before it's ever written. Same class as `new`'s own comment.
        # The target's own header is read fresh, inside the lock, instead
        # of via load_target before it -- same freshness fix as
        # approve/reject/undo/supersede.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Re-reads fresh in case folderadr changed between the pre-lock
            # read and lock acquisition -- operating against a stale folder
            # would be silently wrong.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, lines, encoding_repaired = read_target(path, config, warnings=warnings)
            # version never rewrites its own source (only its BODY is
            # carried into a newly created file) -- encoding_repaired_
            # warning's "the file has been rewritten" claim is never true
            # here; this stays accurate regardless of whether the command
            # goes on to succeed, so it fires right away, not after a write.
            if encoding_repaired:
                warnings.append(encoding_repaired_source_warning(path))

            # One scan shared by all three checks below, avoiding a
            # duplicate scan_decisions call each.
            members = family_members(
                folder, config, filename_info.number, warnings=warnings, exclude_from_encoding_check=path
            )
            latest = latest_in_family(folder, config, filename_info.number, members=members)
            if latest is None:
                raise CommandError(
                    "family-not-found", "Could not resolve this decision's own family.", warnings=warnings
                )
            latest_parsed, latest_header, latest_path = latest

            if len(str(latest_parsed.version + 1)) > config.lenversion:
                raise CommandError(
                    "lenversion-too-small-for-new-version",
                    f"New version {latest_parsed.version + 1} does not fit in lenversion={config.lenversion}.",
                    data={"new_version": latest_parsed.version + 1, "lenversion": config.lenversion},
                    warnings=warnings,
                )

            if latest_path.resolve() != path.resolve():
                # Branching a new version off an older member is allowed
                # only when the actual latest was Rejected.
                allowed = latest_header.status_update == "Rejected" and (
                    latest_parsed.version > filename_info.version
                    or (
                        latest_parsed.version == filename_info.version
                        and (latest_parsed.revision or 0) > (filename_info.revision or 0)
                    )
                )
                if not allowed:
                    # Names the actual latest member as structured data --
                    # the code alone can't carry a version number, and an
                    # agent has no other way to learn it without a separate
                    # `explore` call.
                    raise CommandError(
                        "not-latest-version",
                        "This decision is not the latest version/revision in its family.",
                        data={
                            "latest_file": str(latest_path),
                            "latest_version": latest_parsed.version,
                            "latest_revision": latest_parsed.revision,
                            "latest_status": latest_header.status_update,
                        },
                        warnings=warnings,
                    )

            # A specific reason code, not one collapsed not-eligible-for-
            # version, so the caller knows which recovery action applies.
            reason = ineligibility_reason_for_version_or_revise(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)
            if has_superseded_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    "family-member-superseded",
                    "A sibling decision in this family has already been superseded.",
                    warnings=warnings,
                )
            if has_pending_sibling(folder, config, filename_info.number, members=members):
                raise CommandError(
                    "family-member-pending",
                    "Another decision in this family is still unresolved (Proposed).",
                    warnings=warnings,
                )

            refdate = parse_refdate(flags.get("refdate"))
            validate_refdate_not_in_future(refdate)
            not_before = latest_header.date_update or latest_header.date_create
            if not_before is not None:
                validate_refdate_not_before(refdate, not_before)

            # Unlike `new`, an omitted --scope/--domain defaults to the LATEST
            # family member's own current value, not empty -- and not the
            # branch-target's value either, when branching off an older Rejected
            # sibling.
            scope = flags["scope"] if "scope" in flags else (latest_header.scope or "")
            domain = flags["domain"] if "domain" in flags else (latest_header.domain or "")
            reject_embedded_delimiter(scope, "scope")
            reject_embedded_delimiter(domain, "domain")
            # `title` is re-read from the SOURCE file's own header cell, not a
            # live flag -- a hand-edited or migrated file could already carry
            # a filesystem-unsafe character (e.g. ':', an NTFS Alternate-Data-
            # Stream separator), which build_filename below would otherwise
            # propagate into a real write attempt.
            reject_embedded_delimiter(header.title, "title")
            reject_filesystem_unsafe_title(header.title, "title")
            reject_title_with_no_case_transform_content(header.title, "title")

            template = config.template if flags.get("empty") else read_body(lines)

            record = DecisionRecord(
                number=filename_info.number,
                title=header.title,
                version=latest_parsed.version + 1,
                revision=1 if config.lenrevision > 0 else None,
                scope=scope,
                domain=domain,
                status_create="Proposed",
                date_create=refdate,
            )

            filename = build_filename(config, record)
            new_path = resolve_within(folder, filename)
            if new_path.exists():
                raise CommandError(
                    "file-already-exists",
                    f"File already exists: {filename}",
                    data={"file": filename},
                    warnings=warnings,
                )

            content = build_header(config, record) + template
            # ADR001, part 3: guarantees this write never commits blindly
            # if the lease was reclaimed.
            lock.verify_still_held()
            attempts = atomic_write_text(new_path, content)
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Canonical keyword, not the repo's configured status label.
    return {"created": str(new_path), "status": "Proposed", "warnings": warnings}
