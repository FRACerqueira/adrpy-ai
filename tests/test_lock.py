import os
import threading
import time
from pathlib import Path

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

    # Test-adequacy audit round 4, Finding 3: this used to check only a
    # "stale" substring -- lock.py has TWO warning strings containing it
    # (this success-path one, and the timeout-path one below), so a
    # substring-only check couldn't actually tell them apart.
    assert lock.warnings == [
        "A stale repository lock (from a possibly-crashed or genuinely slow process) was reclaimed "
        "before this operation could proceed."
    ]


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

    Test-adequacy audit round 3 raised this same concern but the fix
    landed as a substring check on two distinct phrases ("timing out"/
    "stale"), not a true exact pin as its own docstring claimed -- round
    4's test-adequacy audit caught the drift between that claim and the
    actual assertion. Now genuinely exact: lock.py has TWO warning
    strings containing "stale" (this one, and the reclaim-then-SUCCEEDED
    one on acquire_repo_lock's success path), so only a full-string
    match can tell them apart with certainty."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"stale-token\n{time.time() - 999}")

    with pytest.raises(LockTimeoutError) as excinfo:
        with acquire_repo_lock(tmp_path, abandon_after=0, wait_ceiling=0, poll_interval=0.05):
            pass

    assert excinfo.value.warnings == [
        "A stale repository lock (from a possibly-crashed or genuinely slow process) was "
        "reclaimed, but the lock could still not be acquired before timing out."
    ]


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


def test_try_create_retries_a_transient_permission_error_on_open(tmp_path, monkeypatch):
    """Round 6 stability re-run, corroborated (Finding A-3, upgraded to
    Medium on independent corroboration -- real cross-process contention
    reliably reproduces PermissionError on this exact os.open call,
    ~14% collision rate under stress): this was the one lock-file
    creation site with no tolerance at all for the same transient
    contention window _read_lock/_unlink_with_retry already retry."""
    lock_path = tmp_path / ".adrpy.lock"
    real_open = lock_module.os.open
    calls = {"count": 0}

    def flaky_open(path, *args, **kwargs):
        if path == lock_path:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(lock_module.os, "open", flaky_open)

    result = lock_module._try_create(lock_path, "some-token")

    assert result is True
    assert calls["count"] == 3
    assert lock_path.read_text().startswith("some-token\n")


def test_try_create_returns_false_when_the_permission_error_persists(tmp_path, monkeypatch):
    """FileExistsError (genuine contention -- someone else already holds
    the lock) already returns False, never raises, so the wait loop's
    own timeout handles it -- a persistent PermissionError past the
    retry budget now gets the identical, already-safe treatment instead
    of escaping raw."""
    lock_path = tmp_path / ".adrpy.lock"

    def always_denied(path, *args, **kwargs):
        if path == lock_path:
            raise PermissionError("Access is denied")
        raise AssertionError("unexpected os.open call")

    monkeypatch.setattr(lock_module.os, "open", always_denied)

    result = lock_module._try_create(lock_path, "some-token")

    assert result is False
    assert not lock_path.exists()


def test_reclaim_if_abandoned_tolerates_a_transient_permission_error_on_stat(tmp_path, monkeypatch):
    """Round 6 stability re-run: related gap found during A-3's
    corroboration, same contention class -- both path.stat() calls in
    the malformed-lock-file fallback only tolerated FileNotFoundError,
    not a transient PermissionError, which could escape this function
    raw, out of acquire_repo_lock's own wait loop entirely."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_bytes(b"")  # malformed: 0 bytes, no parseable timestamp
    old_time = time.time() - 60
    os.utime(lock_path, (old_time, old_time))

    real_stat = Path.stat
    calls = {"count": 0}

    def flaky_stat(self, *args, **kwargs):
        if self == lock_path:
            calls["count"] += 1
            if calls["count"] == 1:
                raise PermissionError("Access is denied")
        return real_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", flaky_stat)

    result = lock_module._reclaim_if_abandoned(lock_path, abandon_after=30)

    assert result is True  # eventually reclaimed once the transient error clears
    assert not lock_path.exists()


def test_reclaim_if_abandoned_returns_false_when_read_lock_itself_persistently_fails(tmp_path, monkeypatch):
    """Round 7 resilience audit, Finding 2 (Medium): _reclaim_if_abandoned's
    own _read_lock() calls (parsed-lock branch) had no tolerance at all for
    a PERSISTENT PermissionError -- unlike its sibling path.stat() calls in
    the malformed-lock-file fallback, hardened in round 6. A persistent
    failure here used to escape raw out of acquire_repo_lock's wait loop,
    losing the purpose-built repository-locked/lock-lost reporting this
    mechanism exists to guarantee. Ownership can't be confirmed either way
    -- the safe default is to abstain (don't reclaim), same as every other
    persistent-failure case in this module."""
    lock_path = tmp_path / ".adrpy.lock"
    lock_path.write_text(f"stale-token\n{time.time() - 999}")

    def always_denied(path):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(lock_module, "_read_lock", always_denied)

    result = lock_module._reclaim_if_abandoned(lock_path, abandon_after=1)

    assert result is False
    assert lock_path.exists()


def test_reclaim_if_abandoned_returns_false_when_only_the_second_read_lock_call_persistently_fails(tmp_path, monkeypatch):
    """Round 8 test-adequacy audit, Finding 2 (Medium): the test above
    blanket-replaces _read_lock, so the FIRST call (line 175) fails and
    the function returns False immediately -- the SECOND call site's own
    `except PermissionError` (the recheck-before-unlink, line ~191-195)
    is never actually reached by that test or any other. This lets the
    first call succeed normally (a genuinely abandoned lock, past
    abandon_after) and fails only the second, proving that specific
    except clause is both reachable and correctly wired, not dead code
    shadowed by the first call's own handling."""
    lock_path = tmp_path / ".adrpy.lock"
    stale_timestamp = time.time() - 999
    lock_path.write_text(f"stale-token\n{stale_timestamp}")

    real_read_lock = lock_module._read_lock
    calls = {"count": 0}

    def flaky_read_lock(path):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_read_lock(path)
        raise PermissionError("Access is denied")

    monkeypatch.setattr(lock_module, "_read_lock", flaky_read_lock)

    result = lock_module._reclaim_if_abandoned(lock_path, abandon_after=1)

    assert result is False
    assert calls["count"] == 2
    assert lock_path.exists()  # abstained -- never reached _unlink_with_retry


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


def test_lock_finally_block_survives_a_read_failure_during_release(tmp_path, monkeypatch):
    """Round 5 stability re-run, Finding 2: _read_lock, called first in
    acquire_repo_lock's own `finally` block to confirm ownership before
    unlinking, was only tolerant of a transient PermissionError up to its
    own retry budget -- any OSError beyond that (or any other OSError
    class, e.g. a genuine I/O failure) used to escape the `finally` block
    raw. That turns a fully successful write into a reported failure and
    skips _unlink_with_retry entirely, leaking the lock file for the full
    ABANDON_AFTER_SECONDS window -- the exact class round 4 already closed
    for _unlink_with_retry itself (see its own docstring), just missing
    from its neighbor called first in this same block."""

    def always_fails(path):
        raise PermissionError("Access is denied")

    monkeypatch.setattr(lock_module, "_read_lock", always_fails)

    with acquire_repo_lock(tmp_path):
        pass  # must not raise on exit despite the release-path read failing


def test_lock_finally_block_does_not_mask_a_real_error_when_release_read_fails(tmp_path, monkeypatch):
    """Companion to the test above: the sharper harm isn't just an
    unrelated leak/crash -- a real CommandError raised from inside the
    `with acquire_repo_lock(...)` body must still be the exception the
    caller sees, not replaced by whatever _read_lock's own failure raises
    from the `finally` block (Python's own finally-supersedes-try
    semantics)."""
    from adrpy.core.errors import CommandError

    def always_fails(path):
        raise OSError("simulated I/O failure")

    monkeypatch.setattr(lock_module, "_read_lock", always_fails)

    with pytest.raises(CommandError) as excinfo:
        with acquire_repo_lock(tmp_path):
            raise CommandError("already-accepted", "boom")

    assert excinfo.value.code == "already-accepted"


def test_repo_lock_verify_still_held_passes_while_this_process_still_owns_it(tmp_path):
    with acquire_repo_lock(tmp_path) as lock:
        lock.verify_still_held()  # must not raise


def test_repo_lock_verify_still_held_raises_lock_lost_when_the_read_itself_fails(tmp_path, monkeypatch):
    """Round 6 stability/resilience re-run (2 independent fronts, cross-
    corroborated -- same defect found by both, no shared context): a
    persistent I/O failure reading the lock file during this check used
    to re-raise as a bare PermissionError -- in migrate's per-candidate
    loop specifically, that meant it was caught by the per-file except
    clause and misreported as THAT candidate's own write failure, even
    though the candidate was never touched, and the loop kept going,
    repeating the same misclassification for every remaining candidate.
    Ownership can't be confirmed either way here -- treat it exactly as
    protectively as a genuine loss, under the same LockLostError
    contract every caller already handles correctly."""
    from adrpy.core.lock import LockLostError

    with acquire_repo_lock(tmp_path) as lock:

        def always_denied(path):
            raise PermissionError("Access is denied")

        monkeypatch.setattr(lock_module, "_read_lock", always_denied)

        with pytest.raises(LockLostError) as excinfo:
            lock.verify_still_held()
        assert excinfo.value.code == "lock-lost"


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


def test_lock_finally_block_never_deletes_another_owners_lock(tmp_path):
    """Round 4 test-adequacy audit, Finding 1: acquire_repo_lock's own
    `finally` block only unlinks the lock file if the on-disk token still
    matches this call's own -- this is what stops a process from deleting
    a lock that was reclaimed-as-abandoned and then re-acquired by
    another process while the first was still finishing its own (now-
    orphaned) critical section. No test ever made the on-disk token
    diverge from the caller's own before release and confirmed the file
    survives untouched."""
    lock_path = tmp_path / ".adrpy.lock"

    with acquire_repo_lock(tmp_path):
        lock_path.write_text(f"someone-else-entirely\n{time.time()}")

    assert lock_path.exists()
    assert lock_path.read_text().startswith("someone-else-entirely\n")


def test_lock_finally_block_rechecks_ownership_immediately_before_unlinking(tmp_path, monkeypatch):
    """Round 5 stability re-run, Finding 6 (narrows, does not fully close
    -- no atomic compare-and-delete exists at the filesystem level): the
    release path's own read-then-unlink was itself a narrower TOCTOU -- if
    a reclaim landed between the ownership check and the unlink call,
    this process could delete the NEW owner's lock file. A true red isn't
    achievable here: the vulnerable window is between two reads that only
    exist once this fix's own second read is added, so there is no
    single-read version of this test that could fail first for the right
    reason -- this is a targeted unit test of the guard itself instead
    (CLAUDE.md's own "red isn't achievable" exception), verified against
    its absence by temporarily reverting just this guard and confirming
    the test then fails (done by hand before committing, not repeated
    here). Simulates the reclaim landing exactly between this finally
    block's two reads by rewriting the lock file inside a monkeypatched
    second call."""
    real_read_lock = lock_module._read_lock
    calls = {"n": 0}
    hijacked_token = "someone-else-entirely"

    def flaky_read_lock(path):
        calls["n"] += 1
        if calls["n"] == 2:
            # Simulates a reclaim landing between this finally block's
            # ownership check (call 1, sees this process's own token) and
            # the unlink -- a different process's lock file appears here,
            # exactly as a genuine reclaim would leave it.
            path.write_text(f"{hijacked_token}\n{time.time()}")
        return real_read_lock(path)

    monkeypatch.setattr(lock_module, "_read_lock", flaky_read_lock)

    with acquire_repo_lock(tmp_path):
        pass

    assert calls["n"] == 2
    lock_path = tmp_path / ".adrpy.lock"
    assert lock_path.exists()
    assert lock_path.read_text().startswith(f"{hijacked_token}\n")


def test_reclaim_if_abandoned_race_guard_blocks_removal_when_the_second_read_differs(tmp_path, monkeypatch):
    """Round 4 test-adequacy audit, Finding 2: _reclaim_if_abandoned's own
    inner race guard (`if _read_lock(path) != existing: return False`)
    re-reads the lock a second time after confirming it's abandoned, and
    only removes it if that second read still matches the first --
    protects against a different process refreshing/reclaiming the lock
    in the narrow window between the two reads. This branch was never
    forced in any existing test."""
    lock_path = tmp_path / ".adrpy.lock"
    stale_timestamp = time.time() - 999
    lock_path.write_text(f"stale-token\n{stale_timestamp}")

    real_read_lock = lock_module._read_lock
    calls = {"count": 0}

    def flaky_read_lock(path):
        calls["count"] += 1
        if calls["count"] == 2:
            # Simulates a different process refreshing/reclaiming the
            # lock between this function's own first and second read.
            return ("a-different-process-own-token", stale_timestamp)
        return real_read_lock(path)

    monkeypatch.setattr(lock_module, "_read_lock", flaky_read_lock)

    result = lock_module._reclaim_if_abandoned(lock_path, abandon_after=1)

    assert result is False
    assert lock_path.exists()
    assert calls["count"] == 2


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
