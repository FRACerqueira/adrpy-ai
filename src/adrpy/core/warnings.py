"""Builds the small set of human-readable warning strings for automatic,
non-fatal actions a command's own dependencies may take silently
otherwise (observability audit): a retried write, a reclaimed stale
lock, orphaned temp-file cleanup, and invalid-byte encoding repair. Every
mutating command's result carries these under "warnings" (an empty list
when nothing happened) so an agent calling the CLI can see them without
needing any external logging -- this is domain information that would
otherwise be discarded before it ever reached anywhere a log could
capture it, not a substitute for real operational logging (which stays
the executor's responsibility, per the project's own args-in/JSON-out
design)."""

import contextlib

from adrpy.core.errors import CommandError


@contextlib.contextmanager
def attach_warnings(warnings):
    """Mechanism-correctness audit round 2 (findings #3/#4), class closure:
    a real side effect already accumulated in `warnings` must survive ANY
    CommandError this same run goes on to raise afterward -- not just the
    raise sites living directly in a command's own cli/ module (already
    threaded explicitly at each site), but also one raised from a shared
    core/ helper the command calls (parse_refdate, validate_refdate_*,
    reject_embedded_delimiter, resolve_within, or a LockTimeoutError
    surfacing its own reclaim warning from acquire_repo_lock). Wrap the
    whole region of a command's `run()` from where `warnings` starts
    accumulating onward.

    Merges rather than overwrites: an error that already carries its own
    warnings (e.g. a LockTimeoutError's stale-lock-reclaim warning) keeps
    them, with this command's own accumulated warnings prepended -- unless
    `error.warnings` is literally this same list (an explicit `warnings=
    warnings` already passed at the raise site), in which case there is
    nothing to merge."""
    try:
        yield
    except CommandError as error:
        if error.warnings is None:
            error.warnings = list(warnings)
        elif error.warnings is not warnings:
            error.warnings = list(warnings) + list(error.warnings)
        raise
    except OSError as error:
        # Mechanism-correctness audit round 3 (resilience finding #1): a
        # real write failure (permission denied, full disk, a
        # PermissionError outlasting atomic_write's retry budget) used to
        # propagate as a bare OSError -- this context manager only caught
        # CommandError, so it bypassed the whole mechanism entirely,
        # reaching __main__'s generic io-error with none of this run's
        # accumulated warnings attached. This is the safety net for every
        # write in the wrapped region; a site that needs to reveal a
        # PARTICULAR partial mutation (e.g. supersede's predecessor
        # already marked Superseded before its successor write failed)
        # still handles its own OSError explicitly, with tailored `data`,
        # before it would ever reach here.
        raise CommandError("io-error", str(error), warnings=list(warnings)) from error


def orphan_cleanup_warning(removed):
    if not removed:
        return None
    names = ", ".join(path.name for path in removed)
    return f"Removed {len(removed)} orphaned temp file(s) left by an earlier interrupted write: {names}."


def retry_warning(attempts):
    if not attempts or attempts <= 1:
        return None
    return f"Write succeeded only after {attempts} attempts due to transient contention."


def encoding_repaired_warning(path):
    return (
        f"{path}: invalid UTF-8 bytes were replaced with U+FFFD while reading; "
        "the original bytes are now lost, since the file has been rewritten."
    )
