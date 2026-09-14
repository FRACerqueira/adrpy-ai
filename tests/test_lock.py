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
