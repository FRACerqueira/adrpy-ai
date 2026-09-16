"""Concurrency lock for any operation that decides "what's the next
number/version" (harness Fase 4).

Deliberate hardening beyond the original: AdrPlus itself has no equivalent
protection (confirmed -- no `Mutex`, `Semaphore`, `lock` statement, or
exclusive `FileShare` anywhere in its source), motivated by an AI agent
being able to fire concurrent calls in a way the original's single
interactive user never needed to. Registered as such, not as fidelity.

`LOCK_FILE_NAME` is reserved and must be excluded from every future scan of
the decisions directory (Fase 6/7) -- it must never appear as an
"unrecognized file" in a report, nor be mistaken for a candidate under
either naming scheme.
"""

import contextlib
import os
import time
import uuid
from pathlib import Path

from adrpy.core.errors import CommandError
from adrpy.core.io_retry import read_with_permission_retry

LOCK_FILE_NAME = ".adrpy.lock"
ABANDON_AFTER_SECONDS = 30
WAIT_CEILING_SECONDS = 10
POLL_INTERVAL_SECONDS = 0.2
# Shared by every transient-I/O retry in this file (unlink, read) -- same
# contention window atomic_write_bytes documents for the identical class
# of Windows "pending delete"/sharing-violation failure.
LOCK_IO_RETRY_ATTEMPTS = 3
LOCK_IO_RETRY_DELAY_SECONDS = 0.05


class LockTimeoutError(CommandError):
    """A CommandError (not a bare Exception) so a genuine timeout surfaces
    as a real, named failure code (resilience audit R4) instead of falling
    through __main__'s catch-all as an internal-error."""

    def __init__(self, detail, warnings=None):
        super().__init__("repository-locked", detail, warnings=warnings)


class LockLostError(CommandError):
    """Round 4 ADR001 (doc/adr/ADR001V01-...): the lock was acquired
    successfully but was reclaimed by another process before this
    command's write could commit -- distinct from LockTimeoutError (never
    acquired the lock at all), so a caller retrying on this code knows
    the repository itself is fine and only this specific race was lost."""

    def __init__(self, detail, warnings=None):
        super().__init__("lock-lost", detail, warnings=warnings)


def _unlink_with_retry(path):
    """Same transient-PermissionError retry as atomic_write_text (Fase 4) --
    a Windows "pending delete"/sharing-violation window under heavy
    concurrent lock churn can make an unlink of a file that genuinely is
    ours fail momentarily.

    Returns True once the file is confirmed gone (removed by this call, or
    already absent), False when removal could not be confirmed. Never
    raises: best-effort, since a lock file left behind is still eligible
    for reclaim later by `_reclaim_if_abandoned` -- but round 4's
    resilience/observability audit found the return value was missing
    entirely (every caller assumed success) and that only PermissionError
    was even caught, so any other OSError during release used to escape
    `acquire_repo_lock`'s own `finally` block raw, turning a fully
    successful write into a reported failure."""
    for attempt in range(LOCK_IO_RETRY_ATTEMPTS):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError:
            if attempt < LOCK_IO_RETRY_ATTEMPTS - 1:
                time.sleep(LOCK_IO_RETRY_DELAY_SECONDS)
        except OSError:
            return False
    return False


def _read_lock(path):
    """Retries a transient PermissionError, the same tolerance
    `_unlink_with_retry`/`atomic_write_bytes` already have for this
    project's own documented contention window (round 4, resilience
    Finding 4) -- called both from the wait loop (every poll) and from
    the release path, so an intolerant read here could abort a wait that
    should have simply retried, or raise out of a `finally` block.

    Round 5 stability re-run, Finding 4, class closure: the retry loop
    itself now lives in core/io_retry.py, shared with core/lifecycle.py's
    own decision-file reads instead of being a second independent copy --
    this call passes this module's own LOCK_IO_RETRY_* tuning explicitly,
    so a future change to either site's numbers can't silently drift the
    other."""
    try:
        raw = read_with_permission_retry(
            lambda: path.read_text(encoding="utf-8"),
            attempts=LOCK_IO_RETRY_ATTEMPTS,
            delay=LOCK_IO_RETRY_DELAY_SECONDS,
        )
    except FileNotFoundError:
        return None
    token, _, timestamp_text = raw.partition("\n")
    try:
        return token, float(timestamp_text)
    except ValueError:
        return None


def _try_create(path, token):
    """Round 4, resilience Finding 2: a process killed (or any other
    OSError, e.g. disk full) between os.open and the write landing used to
    leave a 0-byte/truncated lock file behind with no cleanup -- unlike
    atomic_write_bytes, hardened for this exact class in round 1. Left
    behind, that file is unparseable, which is exactly the case
    `_reclaim_if_abandoned`'s mtime fallback below exists for -- but
    cleaning it up immediately here means a future reclaim isn't the only
    thing standing between a crash and a permanent deadlock."""
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{token}\n{time.time()}")
    except OSError:
        _unlink_with_retry(path)
        raise
    return True


def _reclaim_if_abandoned(path, abandon_after):
    """Removes the lock file only if it is still the exact same abandoned
    lock just inspected -- narrows, but cannot fully close, the race against
    a different process reclaiming (or refreshing) it at the same moment.
    Returns True only when this call's own `_unlink_with_retry` confirms
    the removal happened, not merely attempted (round 4, resilience/
    observability Finding 1a: this used to return True unconditionally,
    producing a false "reclaimed" claim while the lock file was still on
    disk), so the caller can report it (harness Fase 4: a reclaim must
    warn, naming the two possible causes -- a crashed process or a
    genuinely slow one -- since neither can be told apart from here).

    A lock file whose content doesn't parse (e.g. 0 bytes or truncated, as
    `_try_create` above can no longer leave behind itself, but a crash
    mid-write could still produce via a different path) has no timestamp
    to compare against `abandon_after` -- falls back to the file's own
    mtime, or such a lock could never be recognized as abandoned and the
    repository deadlocks permanently (round 4, resilience Finding 2,
    reproduced)."""
    existing = _read_lock(path)
    if existing is not None:
        _, timestamp = existing
        if time.time() - timestamp <= abandon_after:
            return False
        if _read_lock(path) != existing:
            return False
        return _unlink_with_retry(path)

    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        return False
    if time.time() - mtime <= abandon_after:
        return False
    try:
        # Same race-guard intent as the parsed-lock branch above: only
        # remove if it's still the exact same malformed file just observed.
        still_malformed = _read_lock(path) is None and path.stat().st_mtime == mtime
    except FileNotFoundError:
        return False
    if not still_malformed:
        return False
    return _unlink_with_retry(path)


class RepoLock:
    """Yielded by acquire_repo_lock in place of a bare warnings list (round
    4 ADR001): bundles the warnings accumulated so far with the means to
    prove this process still owns the lock immediately before a command's
    final write. No bounded-lease lock without heartbeat/renewal can
    prevent every reclaim of a still-working holder -- this guarantees
    that holder never commits a write believing it still has exclusivity
    when it does not, converting a possible silent collision into a
    clean, explicit failure instead."""

    def __init__(self, path, token, warnings):
        self._path = path
        self._token = token
        self.warnings = warnings

    def verify_still_held(self):
        existing = _read_lock(self._path)
        if existing is None or existing[0] != self._token:
            # No `warnings=` here deliberately: every caller raises this
            # from inside its own attach_warnings(warnings)-wrapped region,
            # which fills in the command's own up-to-date list (possibly
            # grown since this lock's own acquire-time snapshot). Passing
            # this list's own stale copy here would double it instead.
            raise LockLostError(
                f"The repository lock at {self._path} was lost before this write could commit "
                "(reclaimed by another process) -- no write was made."
            )


@contextlib.contextmanager
def acquire_repo_lock(
    decisions_dir,
    abandon_after=ABANDON_AFTER_SECONDS,
    wait_ceiling=WAIT_CEILING_SECONDS,
    poll_interval=POLL_INTERVAL_SECONDS,
):
    """Scope is the root of the whole decisions directory, never a
    subfolder of the specific file being operated on -- a repo organized
    into per-team/per-domain subfolders would otherwise let two operations
    in different subfolders never exclude each other."""
    path = Path(decisions_dir) / LOCK_FILE_NAME
    token = uuid.uuid4().hex
    # time.monotonic(), not time.time(): this deadline is purely in-process
    # (never compared against another process's clock, unlike the reclaim
    # check below), so it must be immune to a wall-clock adjustment (NTP
    # correction) happening mid-wait -- confirmed live that a backward
    # jump made the old time.time()-based deadline never trip, hanging
    # past wait_ceiling for a lock genuinely still held.
    deadline = time.monotonic() + wait_ceiling
    reclaimed_stale_lock = False

    while True:
        if _try_create(path, token):
            break
        if _reclaim_if_abandoned(path, abandon_after):
            reclaimed_stale_lock = True
        if time.monotonic() >= deadline:
            # Mechanism-correctness audit: reclaiming a stale lock right
            # before timing out anyway used to vanish entirely -- the
            # reclaim actually happened (a real side effect, same as
            # the success-path warning below), but nothing in the
            # resulting failure said so.
            timeout_warnings = (
                [
                    "A stale repository lock (from a possibly-crashed or genuinely slow process) was "
                    "reclaimed, but the lock could still not be acquired before timing out."
                ]
                if reclaimed_stale_lock
                else None
            )
            raise LockTimeoutError(
                f"Timed out waiting for the repository lock at {path}", warnings=timeout_warnings
            )
        time.sleep(poll_interval)

    # Observability audit: yields the warnings list the caller should
    # attach to its own result -- reclaiming a stale lock used to be
    # completely silent, even though the harness explicitly requires a
    # warning here.
    warnings = []
    if reclaimed_stale_lock:
        warnings.append(
            "A stale repository lock (from a possibly-crashed or genuinely slow process) was reclaimed "
            "before this operation could proceed."
        )

    lock = RepoLock(path, token, warnings)
    try:
        yield lock
    finally:
        # Round 5 stability re-run, Finding 2: same class round 4 already
        # closed for _unlink_with_retry just below -- any OSError escaping
        # this `finally` block turns a fully successful write into a
        # reported failure (and, since a `finally`-raised exception
        # supersedes whatever was propagating from `try: yield lock`, can
        # mask a real CommandError code as a generic io-error) -- and
        # skips _unlink_with_retry entirely, leaking the lock file for the
        # full ABANDON_AFTER_SECONDS window. _read_lock, called first here,
        # was still exempt: best-effort like its neighbor -- if ownership
        # can't even be confirmed, leave the file for a later reclaim
        # rather than raising or guessing.
        try:
            existing = _read_lock(path)
        except OSError:
            existing = None
        if existing is not None and existing[0] == token:
            # Round 5 stability re-run, Finding 6 (narrows, does not fully
            # close -- no atomic compare-and-delete exists at the
            # filesystem level): re-read immediately before unlinking,
            # the same inner race-guard shape _reclaim_if_abandoned
            # already uses for its own removal decision. If a reclaim
            # lands in exactly this narrower window (between the
            # ownership check above and the unlink), abstain instead of
            # deleting the new owner's lock file.
            try:
                recheck = _read_lock(path)
            except OSError:
                recheck = None
            if recheck == existing:
                _unlink_with_retry(path)
