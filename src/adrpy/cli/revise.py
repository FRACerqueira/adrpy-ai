"""`revise` command: creates a new revision (minor change) of an
Accepted/Rejected decision (harness Fase 7, item 6). Ported from
ReviseCommandHandler.cs. Unlike `version`, revise has no --scope/--domain
and no --empty -- it always carries the source's content forward, and its
scope/domain come from the TARGET file's own header (not the latest
member's), a genuine difference confirmed against the original. --open is
permanently not implemented (see `new.py`'s note).
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
from adrpy.core.security import resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_source_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "still-proposed": "This decision must be Accepted or Rejected before a new revision can be created.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
    "unexpected-status": "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "revise",
        "description": (
            "Creates a new revision (wording fix) of an Accepted/Rejected decision. "
            "Requires the repository's lenrevision to be > 0 (see the `config` command); "
            "fails with revision-not-configured otherwise -- true for any freshly-init'd repository."
        ),
        "arguments": [
            {"name": "file", "type": "string", "required": True, "description": "Path to the decision file."},
            {
                "name": "refdate",
                "type": "string",
                "required": False,
                "description": "Reference date (YYYY-MM-DD); defaults to today.",
            },
        ],
    }


def run(args):
    flags = parse_flags(args, required=("file",), optional=("refdate",), aliases={"f": "file", "r": "refdate"})
    config, root, path = resolve_repo_and_target(flags["file"])

    if config.lenrevision == 0:
        raise CommandError(
            "revision-not-configured", "This repository's config has lenrevision == 0."
        )

    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder))
            if warning:
                warnings.append(warning)

        # Concurrency audit (critical): same reasoning as `version`'s own
        # comment -- family-state read and write must be one critical section.
        #
        # Round 4 ADR001 (doc/adr/ADR001V01-...): the target's own header is
        # now read fresh, inside the lock, instead of via load_target before
        # it -- same freshness fix as approve/reject/undo/supersede/version.
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            filename_info, header, lines, encoding_repaired = read_target(path, config)
            # Round 4 resilience audit, Finding 1: revise never rewrites
            # its own source either -- see version.py's own comment.
            if encoding_repaired:
                warnings.append(encoding_repaired_source_warning(path))

            # Performance backlog item: one scan, shared by all three checks
            # below -- each used to call family_members (and so
            # scan_decisions) on its own (3 scans per invocation).
            members = family_members(folder, config, filename_info.number, warnings=warnings)
            latest = latest_in_family(folder, config, filename_info.number, members=members)
            if latest is None:
                raise CommandError(
                    "family-not-found", "Could not resolve this decision's own family.", warnings=warnings
                )
            latest_parsed, latest_header, latest_path = latest

            if len(str((latest_parsed.revision or 0) + 1)) > config.lenrevision:
                raise CommandError(
                    "lenrevision-too-small-for-new-revision",
                    f"New revision {(latest_parsed.revision or 0) + 1} does not fit in lenrevision={config.lenrevision}.",
                    data={"new_revision": (latest_parsed.revision or 0) + 1, "lenrevision": config.lenrevision},
                    warnings=warnings,
                )

            if latest_path.resolve() != path.resolve():
                # Same branch-off-a-rejected-latest exception as `version`, but
                # revision-only (revise never bumps the version number).
                allowed = latest_header.status_update == "Rejected" and (latest_parsed.revision or 0) > (
                    filename_info.revision or 0
                )
                if not allowed:
                    # Usability audit: names the actual latest member as
                    # structured data -- see `version`'s own comment.
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
            # not-eligible-for-revision.
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

            record = DecisionRecord(
                number=filename_info.number,
                title=header.title,
                version=header.version or 0,
                revision=(header.revision or 0) + 1,
                scope=header.scope,
                domain=header.domain,
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

            content = build_header(config, record) + read_body(lines)
            # ADR001, part 3: guarantees this write never commits blindly
            # if the lease was reclaimed.
            lock.verify_still_held()
            attempts = atomic_write_text(new_path, content)
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Usability audit M4: canonical keyword, not the repo's configured label.
    return {"created": str(new_path), "status": "Proposed", "warnings": warnings}
