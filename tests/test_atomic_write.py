import os
import threading
import time
from pathlib import Path

import pytest

from adrpy.core.atomic_write import (
    atomic_write_bytes,
    atomic_write_chunks,
    atomic_write_text,
    cleanup_orphaned_temp_files,
    normalize_newlines,
)


def test_atomic_write_normalizes_and_creates_file(tmp_path):
    target = tmp_path / "decision.md"

    atomic_write_text(target, "hello\r\nworld")

    assert target.read_bytes() == f"hello{os.linesep}world".encode()


def test_atomic_write_leaves_no_temp_file_behind(tmp_path):
    target = tmp_path / "decision.md"

    atomic_write_text(target, "content")

    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_bytes_returns_the_attempt_count(tmp_path):
    target = tmp_path / "decision.md"

    attempts = atomic_write_bytes(target, b"content")

    assert attempts == 1


def test_atomic_write_reports_more_than_one_attempt_after_transient_retry(tmp_path, monkeypatch):
    """The retry count was computed but never
    returned to the caller, so nothing (not even the command's own
    result) could tell whether a write needed contention-driven retries."""
    target = tmp_path / "decision.md"
    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("simulated transient contention")
        return real_replace(*args, **kwargs)

    monkeypatch.setattr("adrpy.core.atomic_write.os.replace", flaky_replace)
    monkeypatch.setattr("adrpy.core.atomic_write.time.sleep", lambda _seconds: None)

    attempts = atomic_write_bytes(target, b"content")

    assert attempts == 3
    assert target.read_bytes() == b"content"


def test_atomic_write_raises_the_last_error_after_exhausting_all_retries(tmp_path, monkeypatch):
    """No existing test forced ALL
    RETRY_ATTEMPTS to fail -- only 2 of 3, succeeding on the 3rd. A
    persistent PermissionError (outlasting the whole retry budget) must
    propagate as the real error, not hang or swallow it, and the orphaned
    temp file must still be cleaned up on every attempt along the way."""
    from adrpy.core.atomic_write import RETRY_ATTEMPTS

    target = tmp_path / "decision.md"
    calls = {"n": 0}

    def always_fails(*args, **kwargs):
        calls["n"] += 1
        raise PermissionError("persistent contention")

    monkeypatch.setattr("adrpy.core.atomic_write.os.replace", always_fails)
    monkeypatch.setattr("adrpy.core.atomic_write.time.sleep", lambda _seconds: None)

    with pytest.raises(PermissionError):
        atomic_write_bytes(target, b"content")

    assert calls["n"] == RETRY_ATTEMPTS
    assert list(tmp_path.glob("*.tmp")) == []  # no orphan left behind
    assert not target.exists()


def test_atomic_write_text_also_returns_the_attempt_count(tmp_path):
    target = tmp_path / "decision.md"

    attempts = atomic_write_text(target, "content")

    assert attempts == 1


def test_atomic_write_cleans_up_orphan_on_non_permission_oserror(tmp_path, monkeypatch):
    """Only PermissionError triggered the orphan-temp cleanup; any other
    OSError (ENOSPC, a missing parent directory) left
    the temp file behind forever. Confirmed there is nothing transient
    about these -- retrying wouldn't help -- so they must fail fast (no
    retry budget wasted) but still never leak the temp file."""
    target = tmp_path / "decision.md"

    def boom(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("adrpy.core.atomic_write.os.replace", boom)

    with pytest.raises(OSError):
        atomic_write_text(target, "content")

    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_chunks_cleans_up_orphan_when_the_chunk_producer_raises_a_non_oserror(tmp_path):
    """ADR006V01's chunk producer can raise LockLostError (core/lock.py)
    from inside the generator -- not an OSError, so it never hit the
    existing `except OSError` cleanup branch, leaking the temp file
    (found via live reproduction against `rewrite_status_field`, not
    inferred from reading the code alone). Any exception escaping the
    chunk producer, not just OSError, must still leave no orphan behind."""
    target = tmp_path / "decision.md"

    class _SimulatedLockLoss(Exception):
        pass

    def failing_chunks():
        yield b"partial content"
        raise _SimulatedLockLoss("lock stolen mid-stream")

    with pytest.raises(_SimulatedLockLoss):
        atomic_write_chunks(target, failing_chunks)

    assert list(tmp_path.glob("*.tmp")) == []
    assert not target.exists()


def test_atomic_write_failure_before_replace_leaves_target_untouched(tmp_path, monkeypatch):
    target = tmp_path / "decision.md"
    target.write_text("original")

    def boom(*_args, **_kwargs):
        raise OSError("simulated crash before replace")

    monkeypatch.setattr("adrpy.core.atomic_write.os.replace", boom)

    with pytest.raises(OSError):
        atomic_write_text(target, "new content")

    assert target.read_text() == "original"


def test_atomic_write_readers_never_see_partial_content(tmp_path):
    target = tmp_path / "decision.md"
    atomic_write_text(target, "version-0")

    observations = []
    stop = threading.Event()

    def reader():
        # A small pause between reads keeps this a realistic concurrent
        # reader (spaced roughly like separate CLI invocations) rather than
        # a zero-yield busy loop that starves every writer's rename window.
        while not stop.is_set():
            try:
                observations.append(target.read_text())
            except (FileNotFoundError, PermissionError):
                # A reader can transiently hit either during the exact
                # instant of os.replace on Windows -- neither is a partial
                # read, which is the one thing this test must never observe.
                pass
            time.sleep(0.001)

    reader_thread = threading.Thread(target=reader, daemon=True)
    reader_thread.start()

    try:
        for i in range(1, 50):
            atomic_write_text(target, f"version-{i}")
    finally:
        stop.set()
        reader_thread.join(timeout=5)

    assert not reader_thread.is_alive()
    expected_values = {f"version-{i}" for i in range(50)}
    assert set(observations) <= expected_values


def test_cleanup_removes_only_old_temp_files(tmp_path):
    old_temp = tmp_path / "old.tmp"
    old_temp.write_text("stale")
    old_time = time.time() - 60
    os.utime(old_temp, (old_time, old_time))

    fresh_temp = tmp_path / "fresh.tmp"
    fresh_temp.write_text("fresh")

    removed = cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30)

    assert removed == [old_temp]
    assert not old_temp.exists()
    assert fresh_temp.exists()


def test_cleanup_finds_orphaned_temp_files_inside_subfolders_too(tmp_path):
    """Every other scan in this
    codebase (scan_decisions, migrate, explore, init's own numbering) uses
    rglob to also cover subfolders under folderadr; this one used a
    non-recursive glob, so an orphan left inside a subfolder was never
    found or reported -- a housekeeping leak, not a correctness issue
    (temp files never collide by name and are never read by anything)."""
    subfolder = tmp_path / "nested"
    subfolder.mkdir()
    old_temp = subfolder / "old.tmp"
    old_temp.write_text("stale")
    old_time = time.time() - 60
    os.utime(old_temp, (old_time, old_time))

    removed = cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30)

    assert removed == [old_temp]
    assert not old_temp.exists()


def test_cleanup_reports_a_warning_instead_of_raising_when_a_candidate_cannot_be_removed(tmp_path, monkeypatch):
    """This best-effort
    housekeeping call runs BEFORE the repository lock in every one of
    the 8 commands that use it -- a concurrent process's own in-flight
    write could plausibly hold a temp file open (or have already
    removed it) at the exact moment this scan reaches it. A transient
    OSError here must not propagate raw and fail the caller's entire
    command over best-effort cleanup unrelated to what it was actually
    asked to do -- best-effort per candidate instead, matching
    _unlink_with_retry's own established philosophy for this exact
    class of problem, reported as a warning when the caller opts in."""
    old_temp = tmp_path / "old.tmp"
    old_temp.write_text("stale")
    old_time = time.time() - 60
    os.utime(old_temp, (old_time, old_time))

    real_unlink = Path.unlink

    def flaky_unlink(self, *args, **kwargs):
        if self == old_temp:
            raise PermissionError(13, "Access is denied", str(old_temp))
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    warnings = []
    removed = cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30, warnings=warnings)

    assert removed == []  # never raised, just didn't count it as removed
    assert old_temp.exists()  # left in place for a later cleanup pass
    assert len(warnings) == 1
    assert "old.tmp" in warnings[0]

    # Backward compatible: no warnings= at all (the default) never raises either.
    assert cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30) == []


@pytest.mark.parametrize(
    ("text", "expected_lines", "trailing"),
    [
        ("a\nb\nc", ["a", "b", "c"], False),
        ("a\r\nb\r\nc", ["a", "b", "c"], False),
        ("a\rb\rc", ["a", "b", "c"], False),
        ("a\r\nb\nc\r", ["a", "b", "c"], True),  # mixed conventions, trailing \r counts as a terminator
        ("a\nb\n", ["a", "b"], True),
        ("", [], False),
    ],
)
def test_normalize_newlines_handles_any_convention(text, expected_lines, trailing):
    expected = os.linesep.join(expected_lines) + (os.linesep if trailing else "")

    assert normalize_newlines(text) == expected


def test_normalize_newlines_is_idempotent():
    once = normalize_newlines("a\r\nb\nc\r")
    twice = normalize_newlines(once)

    assert once == twice


def test_normalize_then_write_never_doubles_a_cr(tmp_path):
    """Regression: this exact shape (already-terminated content, written
    with the wrong newline mode) doubled every CR into "\\r\\r\\n" in the
    `new` command before atomic_write_text started normalizing itself."""
    target = tmp_path / "decision.md"
    already_crlf_content = "line1\r\nline2\r\n" + "template body\r\n"

    atomic_write_text(target, already_crlf_content)

    assert b"\r\r\n" not in target.read_bytes()


@pytest.mark.parametrize(
    "separator",
    ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "", " ", " "],
    ids=["VT", "FF", "FS", "GS", "RS", "NEL", "LS", "PS"],
)
def test_normalize_newlines_does_not_treat_unicode_separators_as_line_breaks(separator):
    """Confirmed live against the reference tool's own .NET runtime (approve
    on a body containing each of these mid-line): none is treated as a
    line break there -- the body survives byte-for-byte, same line count
    before and after. Only str.splitlines()'s much broader definition of
    "line boundary" treats these as breaks -- a genuine behavioral gap,
    not a deliberate choice (unlike invalid-UTF-8-byte replacement on
    rewrite, separately confirmed live to match the reference tool exactly)."""
    text = f"before{separator}after"
    assert normalize_newlines(text) == text
