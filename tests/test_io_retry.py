import time

import pytest

from adrpy.core.fs import READ_RETRY_ATTEMPTS as IO_RETRY_ATTEMPTS, read_with_permission_retry


def test_succeeds_immediately_when_the_read_never_fails():
    calls = {"count": 0}

    def read():
        calls["count"] += 1
        return "ok"

    assert read_with_permission_retry(read) == "ok"
    assert calls["count"] == 1


def test_retries_a_transient_permission_error_and_then_succeeds():
    """Nothing anywhere proved
    this shared helper's own contract directly -- every exercise of it
    was indirect, through one specific caller's own test."""
    calls = {"count": 0}

    def read():
        calls["count"] += 1
        if calls["count"] < IO_RETRY_ATTEMPTS:
            raise PermissionError("Access is denied")
        return "ok"

    assert read_with_permission_retry(read, delay=0) == "ok"
    assert calls["count"] == IO_RETRY_ATTEMPTS


def test_reraises_the_permission_error_once_attempts_are_exhausted():
    calls = {"count": 0}

    def read():
        calls["count"] += 1
        raise PermissionError("Access is denied")

    with pytest.raises(PermissionError):
        read_with_permission_retry(read, attempts=3, delay=0)

    assert calls["count"] == 3


def test_does_not_retry_any_other_exception_type():
    """FileNotFoundError, or any exception other than PermissionError,
    must propagate on the very first occurrence -- retrying it would
    just waste the delay budget on a condition retrying can never fix."""
    calls = {"count": 0}

    def read():
        calls["count"] += 1
        raise FileNotFoundError("no such file")

    with pytest.raises(FileNotFoundError):
        read_with_permission_retry(read, attempts=3, delay=0)

    assert calls["count"] == 1


def test_attempts_equal_to_one_means_no_retry_at_all():
    calls = {"count": 0}

    def read():
        calls["count"] += 1
        raise PermissionError("Access is denied")

    with pytest.raises(PermissionError):
        read_with_permission_retry(read, attempts=1, delay=0)

    assert calls["count"] == 1


def test_sleeps_between_retries_using_the_given_delay(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda seconds: sleeps.append(seconds))

    calls = {"count": 0}

    def read():
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("Access is denied")
        return "ok"

    assert read_with_permission_retry(read, attempts=5, delay=0.05) == "ok"
    # Two failures before success -> two sleeps, not one per attempt.
    assert sleeps == [0.05, 0.05]
