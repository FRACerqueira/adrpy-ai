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

LOCK_FILE_NAME = ".adrpy.lock"
ABANDON_AFTER_SECONDS = 30
WAIT_CEILING_SECONDS = 10
POLL_INTERVAL_SECONDS = 0.2


class LockTimeoutError(Exception):
    pass


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
    a different process reclaiming (or refreshing) it at the same moment."""
    existing = _read_lock(path)
    if existing is None:
        return
    _, timestamp = existing
    if time.time() - timestamp <= abandon_after:
        return
    if _read_lock(path) == existing:
        path.unlink(missing_ok=True)


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
    deadline = time.time() + wait_ceiling

    while True:
        if _try_create(path, token):
            break
        _reclaim_if_abandoned(path, abandon_after)
        if time.time() >= deadline:
            raise LockTimeoutError(f"Timed out waiting for the repository lock at {path}")
        time.sleep(poll_interval)

    try:
        yield
    finally:
        existing = _read_lock(path)
        if existing is not None and existing[0] == token:
            path.unlink(missing_ok=True)
