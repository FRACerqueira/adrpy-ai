"""Atomic file writes shared by every writer in the project.

Every write goes through a temp file in the same directory, then an atomic
`os.replace` -- never truncate-in-place, so a concurrent reader can never
observe an empty or partially-written file. A short, limited retry absorbs
a transient permission failure (e.g. a Windows "pending delete" state under
a concurrent reader); anything past that surfaces as a real error.
"""

import os
import re
import time
import uuid
from pathlib import Path

RETRY_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 0.05
ORPHAN_MAX_AGE_SECONDS = 30

_REAL_NEWLINE = re.compile(r"\r\n|\r|\n")


def split_real_lines(text):
    """Splits `text` on real line terminators only -- CRLF, lone CR, lone
    LF -- unlike `str.splitlines()`, which also treats several Unicode
    line-separator characters (vertical tab, form feed, FS/GS/RS, NEL,
    LINE/PARAGRAPH SEPARATOR) as breaks. A decision body containing any of
    those mid-line must survive `approve` byte-for-byte, same line count
    before and after -- none of them is a real line break here. Using
    `str.splitlines()` for this would silently corrupt such a body into
    extra CRLF lines.

    Matches str.splitlines()'s own convention of never producing a
    trailing empty element for a trailing terminator (only `re.split`'s
    raw behavior would)."""
    if text == "":
        return []
    parts = _REAL_NEWLINE.split(text)
    if parts[-1] == "":
        parts.pop()
    return parts


def normalize_newlines(text):
    """Splits `text` on ANY real newline convention already present (bare
    "\\n", "\\r\\n", lone "\\r" -- including a different OS's own
    convention) and rejoins using THIS host's `os.linesep`, matching how
    the reference tool carries body content forward between operations
    (discarding whatever terminator the source had). Makes every write's newline
    handling the same single call, regardless of whether the content came
    in already terminated, with bare "\\n", or mixed -- the exact ambiguity
    that caused a real doubled-CR bug in the `new` command."""
    if not text:
        return text
    trailing = text[-1] in ("\n", "\r")
    normalized = os.linesep.join(split_real_lines(text))
    if trailing:
        normalized += os.linesep
    return normalized


def atomic_write_text(path, content):
    """Returns the number of attempts the underlying write actually took
    (see atomic_write_bytes) -- 1 in the overwhelming majority of calls,
    >1 only after absorbing transient contention. Callers that want to
    surface this as a warning (observability) check the return value;
    callers that don't care can simply ignore it, same as before this
    return value existed."""
    return atomic_write_bytes(path, normalize_newlines(content).encode("utf-8"))


def atomic_write_bytes(path, content_bytes):
    """Same atomicity guarantees as atomic_write_text, but no newline
    normalization at all -- for the one real case where that would be
    wrong: `migrate` prepends a header to an existing file's content
    verbatim, whatever line endings it already has -- confirmed the real
    tool doesn't normalize an already-read string either, so a
    hand-written LF file ends up with a CRLF header pasted onto an
    untouched LF body -- mixed endings in one file, by design, not a bug
    to "fix" by normalizing.

    Only retries PermissionError -- the one confirmed-transient failure
    (a Windows "pending delete"/sharing-
    violation window under a concurrent reader). Any other OSError
    (ENOSPC, a missing parent directory) is not transient -- retrying
    wouldn't help -- so it fails on the first occurrence instead of
    wasting the retry budget, but the orphaned temp file is always
    cleaned up first, regardless of which OSError subclass was raised.
    Exponential backoff (not a flat delay) on the PermissionError retry:
    a flat 3x50ms window was empirically only ~68% reliable under an
    aggressive concurrent reader (no pause between reads)."""
    path = Path(path)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    last_error = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            with open(temp_path, "wb") as handle:
                handle.write(content_bytes)
            os.replace(temp_path, path)
            return attempt + 1
        except OSError as error:
            last_error = error
            temp_path.unlink(missing_ok=True)
            if not isinstance(error, PermissionError):
                raise
            time.sleep(RETRY_DELAY_SECONDS * (2**attempt))
    raise last_error


def atomic_write_chunks(path, chunks_factory):
    """Same atomicity guarantees as atomic_write_bytes (temp file in the
    same directory, then an atomic os.replace, with the identical
    transient-PermissionError retry), but streams content from
    `chunks_factory()` -- a zero-arg callable returning a fresh iterable
    of bytes chunks -- instead of requiring the whole content already
    assembled in memory (ADR006V01: a decision's body, or a legacy
    file's own content during `migrate`, has no schema-imposed size
    bound the way header content does).

    `chunks_factory` is called again on every retry attempt, not reused
    across attempts -- a transient PermissionError on the destination
    write must not resume from an already-exhausted source iterator.
    When the chunk producer itself reads from a source file (as
    `migrate`'s own caller does), this means the source read and the
    destination write now share ONE combined retry budget
    (RETRY_ATTEMPTS) instead of two independently-budgeted retries --
    deliberate (ADR006V01's own "Negative Consequences"), not an
    oversight."""
    path = Path(path)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    last_error = None
    for attempt in range(RETRY_ATTEMPTS):
        try:
            with open(temp_path, "wb") as handle:
                for chunk in chunks_factory():
                    handle.write(chunk)
            os.replace(temp_path, path)
            return attempt + 1
        except OSError as error:
            last_error = error
            temp_path.unlink(missing_ok=True)
            if not isinstance(error, PermissionError):
                raise
            time.sleep(RETRY_DELAY_SECONDS * (2**attempt))
        except BaseException:
            # A chunk producer can raise something other than OSError --
            # LockLostError (core/lock.py), from ADR006V01's mid-stream
            # lock re-verification -- which the OSError branch above
            # never catches, leaking this temp file (found live: a
            # LockLostError raised from inside rewrite_status_field's own
            # generator left an orphaned .tmp file the OSError-only
            # cleanup never touched).
            temp_path.unlink(missing_ok=True)
            raise
    raise last_error


def cleanup_orphaned_temp_files(directory, max_age_seconds=ORPHAN_MAX_AGE_SECONDS, warnings=None):
    """Removes leftover `*.tmp` files (from a write interrupted by something
    other than the transient permission failure retried above -- a killed
    process, a full disk) once older than `max_age_seconds`. Returns the
    paths removed, so the caller can warn about it.

    This runs BEFORE the repository lock in every command that calls it --
    a concurrent process's own in-flight write could plausibly hold a temp
    file open (or have already removed it) at the exact moment this scan
    reaches it. Best-effort per candidate, matching
    `_unlink_with_retry`'s own established philosophy for this exact
    class of problem (core/lock.py): a transient OSError here does not
    fail the caller's entire command over best-effort housekeeping
    unrelated to what it was actually asked to do -- left in place for a
    later cleanup pass instead, and reported via `warnings` when given.

    Uses rglob, not glob -- every other scan in this codebase
    (scan_decisions, migrate, explore, init's own numbering) already
    covers subfolders under folderadr; a non-recursive scan here would
    leave an orphan inside a subfolder unfound and unreported (a
    housekeeping leak, not a correctness issue -- temp files never
    collide by name and are never read by anything)."""
    directory = Path(directory)
    now = time.time()
    removed = []
    skipped = []
    for candidate in directory.rglob("*.tmp"):
        try:
            age = now - candidate.stat().st_mtime
        except OSError:
            skipped.append(candidate)
            continue
        if age > max_age_seconds:
            try:
                candidate.unlink(missing_ok=True)
                removed.append(candidate)
            except OSError:
                skipped.append(candidate)
    if warnings is not None and skipped:
        names = ", ".join(path.name for path in skipped)
        warnings.append(
            f"{len(skipped)} orphaned temp file(s) could not be checked/removed (permission denied or "
            f"similar), left for a later cleanup pass: {names}."
        )
    return removed
