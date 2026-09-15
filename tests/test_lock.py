import threading
import time

import pytest

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
