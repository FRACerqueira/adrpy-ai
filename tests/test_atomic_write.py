import os
import threading
import time

import pytest

from adrpy.core.atomic_write import atomic_write_text, cleanup_orphaned_temp_files, normalize_newlines


def test_atomic_write_normalizes_and_creates_file(tmp_path):
    target = tmp_path / "decision.md"

    atomic_write_text(target, "hello\r\nworld")

    assert target.read_bytes() == f"hello{os.linesep}world".encode()


def test_atomic_write_leaves_no_temp_file_behind(tmp_path):
    target = tmp_path / "decision.md"

    atomic_write_text(target, "content")

    assert list(tmp_path.glob("*.tmp")) == []


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
