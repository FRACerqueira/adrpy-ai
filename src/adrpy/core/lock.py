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

LOCK_FILE_NAME = ".adrpy.lock"
ABANDON_AFTER_SECONDS = 30
WAIT_CEILING_SECONDS = 10
POLL_INTERVAL_SECONDS = 0.2
UNLINK_RETRY_ATTEMPTS = 3
UNLINK_RETRY_DELAY_SECONDS = 0.05


class LockTimeoutError(CommandError):
    """A CommandError (not a bare Exception) so a genuine timeout surfaces
    as a real, named failure code (resilience audit R4) instead of falling
    through __main__'s catch-all as an internal-error."""

    def __init__(self, detail):
        super().__init__("repository-locked", detail)


def _unlink_with_retry(path):
    """Same transient-PermissionError retry as atomic_write_text (Fase 4) --
    a Windows "pending delete"/sharing-violation window under heavy
    concurrent lock churn can make an unlink of a file that genuinely is
    ours fail momentarily. Best-effort: swallows a PermissionError that
    outlasts every retry, since a stale lock file left behind is still
    correctly reclaimed later by `_reclaim_if_abandoned`."""
    for _ in range(UNLINK_RETRY_ATTEMPTS):
        try:
            path.unlink(missing_ok=True)
            return
        except PermissionError:
            time.sleep(UNLINK_RETRY_DELAY_SECONDS)


def _read_lock(path):
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    token, _, timestamp_text = raw.partition("\n")
    try:
        return token, float(timestamp_text)
    except ValueError:
        return None


def _try_create(path, token):
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(f"{token}\n{time.time()}")
    return True


def _reclaim_if_abandoned(path, abandon_after):
    """Removes the lock file only if it is still the exact same abandoned
    lock just inspected -- narrows, but cannot fully close, the race against
    a different process reclaiming (or refreshing) it at the same moment.
    Returns True only when this call actually removed a stale lock, so the
    caller can report it (harness Fase 4: a reclaim must warn, naming the
    two possible causes -- a crashed process or a genuinely slow one --
    since neither can be told apart from here)."""
    existing = _read_lock(path)
    if existing is None:
        return False
    _, timestamp = existing
    if time.time() - timestamp <= abandon_after:
        return False
    if _read_lock(path) == existing:
        _unlink_with_retry(path)
        return True
    return False


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
            raise LockTimeoutError(f"Timed out waiting for the repository lock at {path}")
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

    try:
        yield warnings
    finally:
        existing = _read_lock(path)
        if existing is not None and existing[0] == token:
            _unlink_with_retry(path)
