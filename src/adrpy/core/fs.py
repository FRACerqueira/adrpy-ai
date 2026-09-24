"""The file I/O primitives every other module goes through: bounded and
retried reads, deletes, and the two-step write -- `prepare_write` puts
the complete content in a temp file next to the target, `commit_write`
moves it into place. Nothing else in src/adrpy calls Path.read_bytes/
read_text/write_bytes/write_text/unlink or os.replace/os.remove directly
(tests/test_fs.py enforces it).

A write never truncates in place: a reader sees the old file or the new
one, never a partial one. A short retry absorbs a transient
PermissionError (a Windows "pending delete"/sharing-violation window);
any other OSError fails at once. A crash between the two steps leaves at
most a temp file, which `cleanup_orphaned_temp_files` removes later.
"""

import errno
import glob
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from adrpy.core.security import is_within

# Write side: exponential backoff (a flat 3x50ms window was empirically
# only ~68% reliable under an aggressive concurrent reader).
RETRY_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 0.05
# Read side: the lighter case, flat delay.
READ_RETRY_ATTEMPTS = 3
READ_RETRY_DELAY_SECONDS = 0.05
ORPHAN_MAX_AGE_SECONDS = 30

# Which exclusive-create branch commit_write takes. A module constant so a
# test can run the other OS's branch.
_IS_WINDOWS = os.name == "nt"

# prepare_write names its temp file `<target name>.<uuid4 hex>.tmp`; the
# orphan sweeps below match only that exact shape, so no other *.tmp a
# user keeps in the same folder is ever mistaken for one of these.
_OWN_TEMP_SUFFIX = r"\.[0-9a-f]{32}\.tmp"
_OWN_TEMP_NAME = re.compile(r".+" + _OWN_TEMP_SUFFIX)


def retry_on_permission(fn, *, attempts, delay, exponential=False):
    """Calls the zero-arg `fn`, retrying only a PermissionError, up to
    `attempts` calls in total, sleeping `delay` between them (doubled
    after each failure when `exponential`). Any other exception
    propagates on the first occurrence; the PermissionError itself is
    re-raised once the attempts are spent. Returns (result, calls made)."""
    for attempt in range(attempts):
        try:
            return fn(), attempt + 1
        except PermissionError:
            if attempt >= attempts - 1:
                raise
            time.sleep(delay * (2**attempt) if exponential else delay)


def read_with_permission_retry(read, attempts=READ_RETRY_ATTEMPTS, delay=READ_RETRY_DELAY_SECONDS):
    """The read side's retry: `read()`'s own result, flat delay."""
    return retry_on_permission(read, attempts=attempts, delay=delay)[0]


def read_bytes(path):
    """The whole file, with the read side's retry."""
    return read_with_permission_retry(Path(path).read_bytes)


def read_bounded(path, max_bytes, chunk_size):
    """Reads at most `max_bytes` plus one chunk's worth of overrun -- the
    overrun only tells the caller the real file is larger, and is never
    meant to be used as content. Never the whole file regardless of its
    true size. No retry of its own: callers wrap it."""
    chunks = []
    total = 0
    with Path(path).open("rb") as handle:
        while total <= max_bytes:
            more = handle.read(chunk_size)
            if not more:
                break
            chunks.append(more)
            total += len(more)
    return b"".join(chunks)


def unlink_with_retry(path):
    """Deletes `path` (already absent is fine), retrying a transient
    PermissionError with the write side's budget and exponential backoff
    -- an editor, an agent or an antivirus scanner briefly holding the
    file (WinError 32) failed adrpy-skills' remove outright (measured: 40
    of 60 removes under 3 concurrent `list` readers, 0 of 60 with this
    retry; the read side's flat budget was too short). Re-raises once
    retries are exhausted: a delete that could not be made is reported."""
    retry_on_permission(
        lambda: Path(path).unlink(missing_ok=True),
        attempts=RETRY_ATTEMPTS,
        delay=RETRY_DELAY_SECONDS,
        exponential=True,
    )


def _discard(temp_path):
    """Best-effort removal of a temp file this module created. A failure
    here never replaces the error that led to it; whatever is left is an
    orphan the next sweep removes."""
    try:
        temp_path.unlink(missing_ok=True)
    except OSError:
        pass


@dataclass(frozen=True)
class Prepared:
    """A complete temp file waiting to be committed onto `path`."""

    path: Path
    temp_path: Path
    attempts: int


def prepare_write(path, data):
    """Writes the complete new content of `path` into a temp file in the
    same folder, leaving `path` itself untouched. `data` is either bytes,
    or a zero-arg callable returning a fresh iterable of bytes chunks
    (for content that is never held in memory whole). A transient
    PermissionError retries the whole temp write, calling the chunk
    factory again from the start; any failure removes the temp file
    before propagating."""
    path = Path(path)
    temp_path = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")

    def _write_temp():
        try:
            with open(temp_path, "wb") as handle:
                if callable(data):
                    for chunk in data():
                        handle.write(chunk)
                else:
                    handle.write(data)
        except BaseException:
            _discard(temp_path)
            raise

    _, attempts = retry_on_permission(
        _write_temp, attempts=RETRY_ATTEMPTS, delay=RETRY_DELAY_SECONDS, exponential=True
    )
    return Prepared(path=path, temp_path=temp_path, attempts=attempts)


def discard_write(prepared):
    """Drops a prepared write that will not be committed."""
    _discard(prepared.temp_path)


_NO_HARD_LINKS = {errno.EPERM, errno.EOPNOTSUPP, errno.ENOTSUP, errno.ENOSYS}


def _copy_exclusive(source, target):
    """Fallback for filesystems without hard links (exFAT, FAT, some
    network shares): O_EXCL still refuses an existing name, but the copy
    is not atomic -- a crash midway leaves a truncated file, which the
    repository validator reports."""
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o666)
    try:
        with os.fdopen(descriptor, "wb") as out, open(source, "rb") as src:
            while chunk := src.read(1 << 16):
                out.write(chunk)
    except BaseException:
        _discard(target)
        raise


def commit_write(prepared, exclusive=False):
    """Moves a prepared temp file onto its target, retrying a transient
    PermissionError without rewriting the temp file. Returns the number
    of attempts. On any failure the temp file is removed and the target
    is as it was.

    `exclusive=True` creates the target only if the name is free, and
    raises FileExistsError otherwise, the existing file untouched. On
    Windows that is os.rename, which refuses an existing target; on
    POSIX, where rename would replace it, os.link, which refuses too,
    then the temp name is removed (if that removal fails, the target is
    still created and the temp is an orphan for the next sweep)."""
    source, target = prepared.temp_path, prepared.path

    def _apply():
        if not exclusive:
            os.replace(source, target)
        elif _IS_WINDOWS:
            os.rename(source, target)
        else:
            try:
                os.link(source, target)
            except FileExistsError:
                raise
            except OSError as error:
                if error.errno not in _NO_HARD_LINKS:
                    raise
                _copy_exclusive(source, target)

    try:
        _, attempts = retry_on_permission(
            _apply, attempts=RETRY_ATTEMPTS, delay=RETRY_DELAY_SECONDS, exponential=True
        )
    except BaseException:
        _discard(source)
        raise
    if exclusive and not _IS_WINDOWS:
        _discard(source)
    return attempts


def write_prepared(path, data, exclusive=False):
    """prepare_write then commit_write. Returns the attempts both steps
    took together: 1 when neither retried."""
    prepared = prepare_write(path, data)
    return prepared.attempts + commit_write(prepared, exclusive=exclusive) - 1


def cleanup_orphaned_temp_files(directory, max_age_seconds=ORPHAN_MAX_AGE_SECONDS, warnings=None):
    """Removes leftover temp files (from a write interrupted by something
    other than the transient permission failure retried above -- a killed
    process, a full disk) once older than `max_age_seconds`. Returns the
    paths removed, so the caller can warn about it.

    Another process could hold a temp file open (or have already removed
    it) at the exact moment this scan reaches it. Best-effort per
    candidate: a transient OSError here does not
    fail the caller's entire command over best-effort housekeeping
    unrelated to what it was actually asked to do -- left in place for a
    later cleanup pass instead, and reported via `warnings` when given.

    Known limitation (decided, not fixed): the 30s age is measured against
    the temp file's own mtime. On a network share whose server clock runs
    well behind this machine's, a concurrent call can sweep another call's
    still-in-flight temp file; that write then fails instead of being
    retried, since the write cannot tell its temp file was swept. The
    failure surfaces as the calling command's own code for that write: an
    io-error for a single-write command, with nothing committed and
    re-running succeeds; for supersede and reject, a failure before their
    first commit (supersede-successor-write-failed, reject-predecessor-
    write-failed) also with nothing committed, and one after it as
    multi-file-write-partially-applied (data.applied/data.pending); and a
    per-file failure in migrate's migration-write-failed, where re-running
    migrates what is left.

    Uses rglob, not glob -- every other scan in this codebase
    (scan_decisions, migrate, explore, init's own numbering) already
    covers subfolders under folderadr; a non-recursive scan here would
    leave an orphan inside a subfolder unfound and unreported (a
    housekeeping leak, not a correctness issue -- temp files never
    collide by name and are never read by anything)."""
    # is_within: rglob descends into a junction/symlink planted inside
    # the folder, which every other rglob consumer in this codebase
    # already guards against (core/security.py).
    root = Path(directory)
    resolved_root = root.resolve()
    candidates = (
        candidate
        for candidate in root.rglob("*.tmp")
        if _OWN_TEMP_NAME.fullmatch(candidate.name) and is_within(root, candidate, resolved_base=resolved_root)
    )
    return _remove_orphans(candidates, max_age_seconds, warnings)


def cleanup_orphaned_temp_files_for(paths, max_age_seconds=ORPHAN_MAX_AGE_SECONDS, warnings=None):
    """Same sweep as `cleanup_orphaned_temp_files`, but scoped to the temp
    files a write to one of `paths` could have left behind -- only
    `<name>.<uuid4 hex>.tmp` in each path's own parent folder, never a
    recursive scan. For a caller whose write surface is a handful of
    known files inside folders it doesn't own (a user's repository root,
    `.github/instructions/`, `~/.claude/skills/`), where sweeping the
    whole folder would reach content this tool never wrote."""
    candidates = []
    for path in dict.fromkeys(Path(path) for path in paths):
        own_temp = re.compile(re.escape(path.name) + _OWN_TEMP_SUFFIX)
        candidates.extend(
            candidate
            for candidate in path.parent.glob(glob.escape(path.name) + ".*.tmp")
            if own_temp.fullmatch(candidate.name)
        )
    return _remove_orphans(candidates, max_age_seconds, warnings)


def _remove_orphans(candidates, max_age_seconds, warnings):
    now = time.time()
    removed = []
    skipped = []
    for candidate in candidates:
        try:
            age = now - candidate.stat().st_mtime
        except FileNotFoundError:
            # Gone since the scan listed it -- typically a concurrent write
            # finishing its own os.replace. Nothing left to clean up.
            continue
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
