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
