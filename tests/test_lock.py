import os
import threading
import time

import pytest

from adrpy.core import lock as lock_module
from adrpy.core.lock import LockTimeoutError, acquire_repo_lock


def test_lock_serializes_concurrent_acquirers(tmp_path):
    violations = []
    in_critical_section = threading.Event()

    def critical_section():
        with acquire_repo_lock(tmp_path):
            if in_critical_section.is_set():
                violations.append("overlap")
            in_critical_section.set()
            time.sleep(0.02)
            in_critical_section.clear()

    threads = [threading.Thread(target=critical_section) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert violations == []


def test_lock_is_released_after_use(tmp_path):
    with acquire_repo_lock(tmp_path):
        pass

    assert not (tmp_path / ".adrpy.lock").exists()


def test_lock_reclaims_an_abandoned_lock(tmp_path):
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"stale-token\n{time.time() - 999}")

    with acquire_repo_lock(tmp_path, abandon_after=1, wait_ceiling=2, poll_interval=0.05):
        pass

    assert not lock_path.exists()


def test_lock_times_out_on_a_fresh_lock_still_held(tmp_path):
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"holder-token\n{time.time()}")

    with pytest.raises(LockTimeoutError):
        with acquire_repo_lock(tmp_path, abandon_after=999, wait_ceiling=0.3, poll_interval=0.05):
            pass


def test_lock_reports_when_a_stale_lock_was_reclaimed(tmp_path):
    """Observability audit: reclaiming a stale lock (a possibly-crashed or
    genuinely-slow process) happened completely silently -- nothing
    anywhere reported that it occurred, even though the harness (Fase 4)
    explicitly calls for a warning naming the two possible causes."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"stale-token\n{time.time() - 999}")

    with acquire_repo_lock(tmp_path, abandon_after=1, wait_ceiling=2, poll_interval=0.05) as lock:
        pass

    assert any("stale" in w.lower() for w in lock.warnings)


def test_lock_reports_no_warnings_when_acquired_cleanly(tmp_path):
    with acquire_repo_lock(tmp_path) as lock:
        pass

    assert lock.warnings == []


def test_lock_timeout_is_a_command_error(tmp_path):
    """Resilience audit R4: LockTimeoutError was a bare Exception, so once
    the lock is actually wired into a command (see the concurrency audit's
    critical finding), a genuine timeout would fall through __main__'s
    catch-all as a raw internal-error instead of a real, named failure
    code an agent could recognize and retry on."""
    from adrpy.core.errors import CommandError

    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"holder-token\n{time.time()}")

    with pytest.raises(CommandError) as excinfo:
        with acquire_repo_lock(tmp_path, abandon_after=999, wait_ceiling=0.3, poll_interval=0.05):
            pass

    assert excinfo.value.code == "repository-locked"


def test_lock_timeout_after_reclaiming_a_stale_lock_still_warns(tmp_path):
    """Mechanism-correctness audit round 2: reclaiming a stale lock is a
    real side effect, even when this process still can't acquire the lock
    before its own wait_ceiling expires (here: the ceiling is already
    exhausted by the time the reclaim itself finishes, on the very first
    iteration -- not a multi-iteration race against a third process, a
    harder scenario to construct deterministically). That reclaim used to
    vanish completely from the resulting LockTimeoutError -- exactly the
    same class of bug as a command's own warnings being dropped on an
    unrelated later failure.

    Test-adequacy audit round 3: the assertion below now pins the exact
    timeout-specific warning text, not just "stale" -- lock.py has TWO
    warning strings containing that substring (this one, and the
    reclaim-then-SUCCEEDED one on acquire_repo_lock's success path), so a
    substring-only check couldn't actually tell them apart."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"stale-token\n{time.time() - 999}")

    with pytest.raises(LockTimeoutError) as excinfo:
        with acquire_repo_lock(tmp_path, abandon_after=0, wait_ceiling=0, poll_interval=0.05):
            pass

    assert excinfo.value.warnings
    assert any("timing out" in w.lower() for w in excinfo.value.warnings)
    assert any("stale" in w.lower() for w in excinfo.value.warnings)


def test_lock_reclaims_a_malformed_lock_file_left_by_a_crash(tmp_path):
    """Resilience audit round 4, Finding 2, reproduced: a lock file left
    partially written (0 bytes, or otherwise unparseable) by a process
    killed between os.open and a successful close used to be permanently
    unreclaimable -- _read_lock returns None for anything that doesn't
    parse as "token\\ntimestamp", and _reclaim_if_abandoned treated
    `existing is None` as "no lock, nothing to reclaim" regardless of the
    file's age, deadlocking the repository until a human deleted it by
    hand. Falls back to the file's own mtime when the content is
    unparseable."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text("")  # malformed: empty, unparseable
    old = time.time() - 999
    os.utime(lock_path, (old, old))

    with acquire_repo_lock(tmp_path, abandon_after=1, wait_ceiling=2, poll_interval=0.05):
        pass

    assert not lock_path.exists()


def test_reclaim_if_abandoned_returns_false_when_the_unlink_itself_fails(tmp_path, monkeypatch):
    """Resilience/observability audit round 4, Finding 1a: _reclaim_if_
    abandoned used to unconditionally return True regardless of whether
    the unlink actually succeeded, producing a false "reclaimed" claim
    (and a false stale-lock warning) even when the stale lock file was
    still physically on disk afterward."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"stale-token\n{time.time() - 999}")

    def failing_unlink(self, missing_ok=False):
        raise OSError(5, "Access is denied")

    monkeypatch.setattr(lock_module.Path, "unlink", failing_unlink)

    result = lock_module._reclaim_if_abandoned(lock_path, abandon_after=1)

    assert result is False
    assert lock_path.exists()


def test_unlink_with_retry_returns_true_on_success(tmp_path):
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text("token\n123")

    assert lock_module._unlink_with_retry(lock_path) is True
    assert not lock_path.exists()


def test_unlink_with_retry_swallows_a_persistent_non_permission_oserror(tmp_path, monkeypatch):
    """Observability audit round 4, Finding 1: _unlink_with_retry only
    retried/swallowed PermissionError and had no return value at all, so
    a caller (e.g. the release path in acquire_repo_lock's `finally`)
    could never tell whether the file was actually removed -- and any
    other OSError propagated raw out of that `finally` block, turning a
    fully successful write into a reported CommandError("io-error")."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text("token\n123")

    def failing_unlink(self, missing_ok=False):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(lock_module.Path, "unlink", failing_unlink)

    result = lock_module._unlink_with_retry(lock_path)

    assert result is False


def test_try_create_cleans_up_the_lock_file_when_the_write_fails(tmp_path, monkeypatch):
    """Resilience audit round 4, Finding 2: unlike atomic_write_bytes
    (hardened for this exact class in round 1), _try_create left the
    just-created (empty) lock file behind on any OSError during the
    write -- the direct mechanism behind the malformed/unreclaimable
    lock file covered above."""
    lock_path = tmp_path / ".adrpy.lock"

    class _FailingHandle:
        def __init__(self, fd):
            self._fd = fd

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            os.close(self._fd)
            return False

        def write(self, data):
            raise OSError(28, "No space left on device")

    monkeypatch.setattr(lock_module.os, "fdopen", lambda fd, *a, **k: _FailingHandle(fd))

    with pytest.raises(OSError):
        lock_module._try_create(lock_path, "some-token")

    assert not lock_path.exists()


def test_read_lock_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """Resilience audit round 4, Finding 4: _read_lock had no
    PermissionError tolerance at all, unlike _unlink_with_retry/
    atomic_write_bytes in this same project, which both document this as
    a confirmed, recurring condition under heavy concurrent lock churn --
    _read_lock is called both from the wait loop (every poll) and from
    the release path, so an intolerant read there can abort a wait that
    should have simply retried."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text("token\n123")

    real_read_text = lock_module.Path.read_text
    calls = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("Access is denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(lock_module.Path, "read_text", flaky_read_text)

    result = lock_module._read_lock(lock_path)

    assert result == ("token", 123.0)
    assert calls["count"] == 3


def test_read_lock_raises_when_the_permission_error_persists(tmp_path, monkeypatch):
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text("token\n123")

    def always_denied(self, *args, **kwargs):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(lock_module.Path, "read_text", always_denied)

    with pytest.raises(PermissionError):
        lock_module._read_lock(lock_path)


def test_repo_lock_verify_still_held_passes_while_this_process_still_owns_it(tmp_path):
    with acquire_repo_lock(tmp_path) as lock:
        lock.verify_still_held()  # must not raise


def test_repo_lock_verify_still_held_raises_lock_lost_when_the_token_changed(tmp_path):
    """Round 4 ADR001, part 3: a different process reclaiming the lock
    file mid-critical-section (simulated here directly, matching a real
    reclaim's own effect) must be detected before the caller's next write
    -- LockLostError, not a silent pass."""
    from adrpy.core.lock import LockLostError

    with acquire_repo_lock(tmp_path) as lock:
        (tmp_path / ".adrpy.lock").write_text(f"someone-else\n{time.time()}")
        with pytest.raises(LockLostError) as excinfo:
            lock.verify_still_held()
        assert excinfo.value.code == "lock-lost"


def test_repo_lock_verify_still_held_raises_lock_lost_when_the_file_is_gone(tmp_path):
    from adrpy.core.lock import LockLostError

    with acquire_repo_lock(tmp_path) as lock:
        (tmp_path / ".adrpy.lock").unlink()
        with pytest.raises(LockLostError):
            lock.verify_still_held()


def test_wait_ceiling_uses_monotonic_clock_not_wall_clock(tmp_path, monkeypatch):
    """Resilience audit R5: the wait-deadline used time.time(), so a
    stalled/backward-jumping wall clock (NTP correction) made the deadline
    check `time.time() >= deadline` never trip -- acquire_repo_lock would
    wait far past its own wait_ceiling for a lock genuinely still held.
    time.monotonic() is immune to wall-clock adjustments by definition;
    only the reclaim check's cross-process age comparison needs the wall
    clock (a timestamp written by a different process can't be compared
    against this process's monotonic clock)."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"holder-token\n{time.time()}")

    frozen = time.time()
    monkeypatch.setattr("adrpy.core.lock.time.time", lambda: frozen)

    result = {}

    def attempt():
        try:
            with acquire_repo_lock(tmp_path, abandon_after=999, wait_ceiling=0.3, poll_interval=0.05):
                pass
        except LockTimeoutError:
            result["timed_out"] = True
        except Exception as error:  # pragma: no cover -- diagnostic only
            result["error"] = error

    thread = threading.Thread(target=attempt, daemon=True)
    thread.start()
    thread.join(timeout=2.0)

    assert not thread.is_alive(), "acquire_repo_lock hung past its wait_ceiling under a frozen wall clock"
    assert result.get("timed_out") is True
