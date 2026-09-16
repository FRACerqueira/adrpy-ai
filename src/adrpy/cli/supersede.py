"""`supersede` command: marks an Accepted decision as Superseded and
creates its successor (harness Fase 7, item 5). Ported from
SupersedeCommandHandler.cs. The successor never copies the predecessor's
body (always starts from the config's default template) and its filename
suffix is unconditional, never a collision-disambiguator. `--open` is
permanently not implemented (see `new.py`'s note).
"""

from adrpy.core.args import parse_flags
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text, cleanup_orphaned_temp_files
from adrpy.core.lifecycle import (
    ineligibility_reason_for_supersede,
    mark_superseded,
    next_number,
    parse_refdate,
    read_target,
    resolve_repo_and_target,
    scan_decisions,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)
from adrpy.core.lock import LockLostError, acquire_repo_lock
from adrpy.core.naming import build_filename
from adrpy.core.security import reject_embedded_delimiter, resolve_within
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning

_INELIGIBILITY_DETAILS = {
    "still-proposed": "This decision must be Accepted before it can be superseded; it is still Proposed.",
    "already-rejected": "This decision was Rejected, not Accepted; only Accepted decisions can be superseded.",
    "already-superseded": "This decision has already been superseded.",
    "not-proposed": "This decision's own status is not Proposed.",
    "unexpected-status": "This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell).",
}


def describe():
    return {
        "name": "supersede",
        "description": (
            "Marks an Accepted decision as Superseded and creates its successor. "
            "This is two writes in sequence, not one: a failure creating the successor "
            "(supersede-successor-write-failed) means success=false even though the predecessor "
            "was already committed to Superseded -- that code's own `data.predecessor`/"
            "`data.predecessor_status` names the file already mutated despite the overall failure "
            "(a lock lost before this SECOND write also surfaces this same code/data, not lock-lost). "
            "May instead fail with repository-locked (lock never acquired) or lock-lost (lost before the "
            "FIRST write) -- in both of those cases no write was made at all. May also fail with "
            "folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while "
            "this call was acquiring the lock -- no write was made either way; retry."
        ),
        "arguments": [
            {
                "name": "file",
                "type": "string",
                "required": True,
                "description": "Path to the decision file. A bare name with no extension gets '.md' appended.",
            },
            {
                "name": "domain",
                "type": "string",
                "required": False,
                "description": "Domain for the successor; defaults to the predecessor's own value.",
            },
            {
                "name": "scope",
                "type": "string",
                "required": False,
                "description": "Scope for the successor; defaults to the predecessor's own value.",
            },
            {
                "name": "refdate",
                "type": "string",
                "required": False,
                "description": "Reference date (YYYY-MM-DD); defaults to today.",
            },
        ],
    }


def run(args):
    flags = parse_flags(
        args,
        required=("file",),
        optional=("domain", "scope", "refdate"),
        aliases={"f": "file", "d": "domain", "s": "scope", "r": "refdate"},
    )
    config, root, path = resolve_repo_and_target(flags["file"])
    folder = resolve_within(root, config.folderadr)
    warnings = []
    with attach_warnings(warnings):
        if folder.is_dir():
            warning = orphan_cleanup_warning(cleanup_orphaned_temp_files(folder, warnings=warnings))
            if warning:
                warnings.append(warning)

        # Concurrency audit (critical): same next-number race as `new` -- see
        # that command's comment. Also covers mark_superseded's mutation of
        # the predecessor, so a concurrent scan by another command never
        # observes the predecessor half-transitioned.
        #
        # Round 4 ADR001 (doc/adr/ADR001V01-...): the predecessor's own
        # header/lines are now read fresh, inside the lock, instead of
        # before it -- previously, two concurrent supersede calls on the
        # SAME predecessor each wrote it from their own stale, pre-lock
        # snapshot; the lock only ever prevented a successor NUMBER
        # collision, not this (stability audit Finding 2, reproduced: two
        # live successors, only one referenced by the predecessor at all).
        with acquire_repo_lock(folder) as lock:
            warnings.extend(lock.warnings)
            # Round 6 stability re-run, root cause shared by 8 call
            # sites -- see approve.py's own comment.
            config = verify_folderadr_unchanged_since_lock(
                root / "adr-config.adrplus", config.folderadr, warnings=warnings
            )
            filename_info, header, lines, encoding_repaired = read_target(path, config)

            # Usability audit: a specific reason code instead of one collapsed
            # not-eligible-for-supersede.
            reason = ineligibility_reason_for_supersede(header)
            if reason is not None:
                raise CommandError(reason, _INELIGIBILITY_DETAILS[reason], warnings=warnings)

            refdate = parse_refdate(flags.get("refdate"))
            validate_refdate_not_in_future(refdate)
            not_before = header.date_update or header.date_create
            if not_before is not None:
                validate_refdate_not_before(refdate, not_before)

            # Unlike `new`, an omitted --scope/--domain defaults to the
            # predecessor's own current value, not empty.
            scope = flags["scope"] if "scope" in flags else (header.scope or "")
            domain = flags["domain"] if "domain" in flags else (header.domain or "")
            reject_embedded_delimiter(scope, "scope")
            reject_embedded_delimiter(domain, "domain")

            successor_number = next_number(scan_decisions(folder, config, warnings=warnings))

            successor = DecisionRecord(
                number=successor_number,
                # The successor's title comes from the predecessor's FILENAME
                # segment (already case-transformed), not its header's prose
                # title -- confirmed via live comparison: SupersedeCommandHandler
                # builds its new AdrRecord from `infoadr.Title` (AdrFileNameComponents'
                # own property, filename-derived), not `infoadr.Header.Title`.
                title=filename_info.title,
                version=1,
                revision=1 if config.lenrevision > 0 else None,
                scope=scope,
                domain=domain,
                status_create="Proposed",
                date_create=refdate,
                superseded=filename_info.number,
            )
            filename = build_filename(config, successor)
            successor_path = resolve_within(folder, filename)
            if successor_path.exists():
                raise CommandError(
                    "file-already-exists",
                    f"File already exists: {filename}",
                    data={"file": filename},
                    warnings=warnings,
                )

            try:
                # ADR001, part 3: guarantees the predecessor write below
                # never commits blindly if the lease was reclaimed.
                lock.verify_still_held()
                _record, _content, attempts = mark_superseded(
                    path, config, lines, header, filename_info, successor_number, refdate
                )
                # Round 4 resilience audit, Finding 1: only true once the
                # write above has actually happened -- see approve.py's
                # own comment.
                if encoding_repaired:
                    warnings.append(encoding_repaired_warning(path))
            except OSError as error:
                # Nothing has been written yet at this point (the
                # predecessor's own mutation IS this write) -- the
                # generic attach_warnings safety net's io-error is
                # already the right shape, just give it a command-
                # specific code for discoverability.
                raise CommandError(
                    "supersede-write-failed", f"{path}: {error}", warnings=warnings
                ) from error
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

            content = build_header(config, successor) + config.template
            try:
                # ADR001, part 3: this command's SECOND write -- guarantees
                # it never commits blindly either, on its own.
                lock.verify_still_held()
                attempts = atomic_write_text(successor_path, content)
            except (OSError, LockLostError) as error:
                # Mechanism-correctness audit round 3 (resilience finding
                # #1), the worst instance found: by this point the
                # predecessor has ALREADY been marked Superseded for real
                # (the write above already succeeded) -- data names that
                # partial mutation explicitly, so a caller doesn't have to
                # infer an orphaned family state from a generic io-error.
                #
                # Round 5 stability re-run, Finding 3: LockLostError used
                # to bypass this handler entirely (only OSError was
                # caught), so a caller saw the generic, dataless "no write
                # was made" lock-lost message even though the predecessor
                # write above already committed for real -- same orphaned-
                # family risk, just a different trigger. Reuses this
                # command's own existing code/data shape rather than
                # inventing a parallel one.
                raise CommandError(
                    "supersede-successor-write-failed",
                    f"{successor_path}: {error}",
                    data={
                        "predecessor": str(path),
                        "predecessor_status": "Superseded",
                        "intended_successor": str(successor_path),
                    },
                    warnings=warnings,
                ) from error
            warning = retry_warning(attempts)
            if warning:
                warnings.append(warning)

    # Usability audit M4: canonical keyword, not the repo's configured label.
    return {"predecessor": str(path), "created": str(successor_path), "status": "Proposed", "warnings": warnings}
