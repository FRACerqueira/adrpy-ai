"""`version` command: creates a new major version of an Accepted/Rejected
decision (harness Fase 7, item 6). Ported from VersionCommandHandler.cs.
`--open` is permanently not implemented (see `new.py`'s note).
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
)
from adrpy.core.lock import acquire_repo_lock
from adrpy.core.naming import build_filename
from adrpy.core.security import reject_embedded_delimiter, resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "still-proposed": "This decision must be Accepted or Rejected before a new version can be created.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
    "unexpected-status": "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "version",
        "description": "Creates a new major version of an Accepted/Rejected decision.",
        "arguments": [
            {"name": "file", "type": "string", "required": True, "description": "Path to the decision file."},
            {
                "name": "domain",
                "type": "string",
                "required": False,
                "description": "Domain for the new version; defaults to the latest version's own value.",
            },
            {
                "name": "scope",
                "type": "string",
                "required": False,
                "description": "Scope for the new version; defaults to the latest version's own value.",
            },
            {
                "name": "refdate",
                "type": "string",
                "required": False,
                "description": "Reference date (YYYY-MM-DD); defaults to today.",
            },
            {
                "name": "empty",
                "type": "switch",
                "required": False,
                # Usability audit A2: this is presence-only (`--empty` with
                # no value, like a getopt flag) -- confirmed live that
                # `--empty true`/`--empty false` both fail with "Unknown
                # argument", not a real boolean value flag. Labeled
                # "boolean" before, which reads as accepting an explicit
                # value the same way `config --disableplugins` does.
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
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder))
            if warning:
                warnings.append(warning)

        # Concurrency audit (critical): the family-state read (latest/sibling
        # checks) and the eventual write must be one critical section -- a
        # concurrent supersede/approve/etc. on a sibling could otherwise slip
        # in between, and this call's next-version-number decision could go
        # stale before it's ever written. Same class as `new`'s own comment.
        #
        # Round 4 ADR001 (doc/adr/ADR001V01-...): the target's own header is
        # now read fresh, inside the lock, instead of via load_target before
        # it -- same freshness fix as approve/reject/undo/supersede.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            filename_info, header, lines, encoding_repaired = read_target(path, config)
            if encoding_repaired:
                warnings.append(encoding_repaired_warning(path))

            # Performance backlog item: one scan, shared by all three checks
            # below -- each used to call family_members (and so
            # scan_decisions) on its own (3 scans per invocation).
            members = family_members(folder, config, filename_info.number)
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
                # Branching a new version off an older member is allowed only when
                # the actual latest was Rejected -- the harness's own documented
                # exception (Fase 7 item 6).
                allowed = latest_header.status_update == "Rejected" and (
                    latest_parsed.version > filename_info.version
                    or (
                        latest_parsed.version == filename_info.version
                        and (latest_parsed.revision or 0) > (filename_info.revision or 0)
                    )
                )
                if not allowed:
                    # Usability audit: names the actual latest member as
                    # structured data -- the code alone can't carry a version
                    # number, and an agent has no other way to learn it
                    # without a separate `explore` call.
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

            # Usability audit: a specific reason code instead of one collapsed
            # not-eligible-for-version.
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
            # sibling (confirmed in VersionCommandHandler.cs).
            scope = flags["scope"] if "scope" in flags else (latest_header.scope or "")
            domain = flags["domain"] if "domain" in flags else (latest_header.domain or "")
            reject_embedded_delimiter(scope, "scope")
            reject_embedded_delimiter(domain, "domain")

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

    # Usability audit M4: canonical keyword, not the repo's configured label.
    return {"created": str(new_path), "status": "Proposed", "warnings": warnings}
