import os
import threading
import time
from pathlib import Path

import pytest

from adrpy.core.atomic_write import (
    atomic_write_bytes,
    atomic_write_chunks,
    atomic_write_text,
    normalize_newlines,
)
from adrpy.core.fs import cleanup_orphaned_temp_files

# The 32-hex shape of the temp files earlier builds wrote, still swept; the
# current one is its first 16 hex digits.
OWN_TEMP_HEX = "0123456789abcdef0123456789abcdef"


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

    monkeypatch.setattr("adrpy.core.fs.os.replace", flaky_replace)
    monkeypatch.setattr("adrpy.core.fs.time.sleep", lambda _seconds: None)

    attempts = atomic_write_bytes(target, b"content")

    assert attempts == 3
    assert target.read_bytes() == b"content"


def test_atomic_write_raises_the_last_error_after_exhausting_all_retries(tmp_path, monkeypatch):
    """No existing test forced ALL
    RETRY_ATTEMPTS to fail -- only 2 of 3, succeeding on the 3rd. A
    persistent PermissionError (outlasting the whole retry budget) must
    propagate as the real error, not hang or swallow it, and the orphaned
    temp file must still be cleaned up on every attempt along the way."""
    from adrpy.core.fs import RETRY_ATTEMPTS

    target = tmp_path / "decision.md"
    calls = {"n": 0}

    def always_fails(*args, **kwargs):
        calls["n"] += 1
        raise PermissionError("persistent contention")

    monkeypatch.setattr("adrpy.core.fs.os.replace", always_fails)
    monkeypatch.setattr("adrpy.core.fs.time.sleep", lambda _seconds: None)

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

    monkeypatch.setattr("adrpy.core.fs.os.replace", boom)

    with pytest.raises(OSError):
        atomic_write_text(target, "content")

    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_bytes_cleans_up_orphan_on_a_non_oserror_mid_write(tmp_path, monkeypatch):
    """Round 35 resilience front: a KeyboardInterrupt (or any other
    non-OSError) raised during the write or the os.replace call bypassed
    the existing `except OSError` cleanup entirely, leaking the temp file
    -- reproduced live against adrpy-skills' installer.py (patched
    os.replace to raise KeyboardInterrupt, found the .tmp file left behind
    in the target directory, permanently, until a human deleted it by
    hand). Any exception escaping mid-write, not just OSError, must still
    leave no orphan behind -- same fix shape as atomic_write_chunks's own
    chunk-producer case above."""
    target = tmp_path / "decision.md"

    def boom(*_args, **_kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr("adrpy.core.fs.os.replace", boom)

    with pytest.raises(KeyboardInterrupt):
        atomic_write_text(target, "content")

    assert list(tmp_path.glob("*.tmp")) == []
    assert not target.exists()


def test_atomic_write_chunks_cleans_up_orphan_when_the_chunk_producer_raises_a_non_oserror(tmp_path):
    """ADR006V01's chunk producer can raise something other than an
    OSError from inside the generator -- it never hits the `except
    OSError` cleanup branch. Any exception escaping the chunk producer,
    not just OSError, must still leave no orphan behind."""
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

    monkeypatch.setattr("adrpy.core.fs.os.replace", boom)

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
    old_temp = tmp_path / f"old.md.{OWN_TEMP_HEX}.tmp"
    old_temp.write_text("stale")
    old_time = time.time() - 60
    os.utime(old_temp, (old_time, old_time))

    fresh_temp = tmp_path / f"fresh.md.{OWN_TEMP_HEX}.tmp"
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
    old_temp = subfolder / f"old.md.{OWN_TEMP_HEX}.tmp"
    old_temp.write_text("stale")
    old_time = time.time() - 60
    os.utime(old_temp, (old_time, old_time))

    removed = cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30)

    assert removed == [old_temp]
    assert not old_temp.exists()


def test_cleanup_reports_a_warning_instead_of_raising_when_a_candidate_cannot_be_removed(tmp_path, monkeypatch):
    """Another process could hold a temp file open (or have already
    removed it) at the exact moment this scan reaches it. A transient
    OSError here must not propagate raw and fail the caller's entire
    command over best-effort cleanup unrelated to what it was actually
    asked to do -- best-effort per candidate instead, reported as a
    warning when the caller opts in."""
    old_temp = tmp_path / f"old.md.{OWN_TEMP_HEX}.tmp"
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
    assert old_temp.name in warnings[0]

    # Backward compatible: no warnings= at all (the default) never raises either.
    assert cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30) == []


@pytest.mark.parametrize(
    "name",
    [
        "notes.tmp",
        "0001-decision.md.tmp",
        f"0001-decision.md.{OWN_TEMP_HEX[:31]}.tmp",
        f"0001-decision.md.{OWN_TEMP_HEX}0.tmp",
        f"0001-decision.md.{OWN_TEMP_HEX.upper()}.tmp",
        f"0001-decision.md.{OWN_TEMP_HEX}.tmp.bak",
        f".{OWN_TEMP_HEX}.tmp",
    ],
)
def test_cleanup_never_removes_a_tmp_file_atomic_write_could_not_have_created(tmp_path, name):
    # atomic_write_bytes/atomic_write_chunks name their temp file
    # `<target name>.<uuid4 hex>.tmp` -- any other *.tmp in the same folder
    # is the user's, however old.
    foreign = tmp_path / name
    foreign.write_text("user data")
    old_time = time.time() - 60
    os.utime(foreign, (old_time, old_time))

    removed = cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30)

    assert removed == []
    assert foreign.exists()


def test_cleanup_still_removes_an_orphan_named_exactly_as_atomic_write_names_it(tmp_path):
    orphan = tmp_path / f"0001-decision.md.{OWN_TEMP_HEX}.tmp"
    orphan.write_text("stale")
    old_time = time.time() - 60
    os.utime(orphan, (old_time, old_time))

    removed = cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30)

    assert removed == [orphan]
    assert not orphan.exists()


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


def test_cleanup_never_follows_a_link_out_of_the_swept_folder(tmp_path):
    import subprocess
    import sys

    folder, outside = tmp_path / "decisions", tmp_path / "outside"
    folder.mkdir()
    outside.mkdir()
    victim = outside / f"notes.md.{OWN_TEMP_HEX}.tmp"
    victim.write_text("user data")
    old_time = time.time() - 60
    os.utime(victim, (old_time, old_time))
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(folder / "sub"), str(outside)], check=True, capture_output=True)
    else:
        os.symlink(outside, folder / "sub", target_is_directory=True)

    removed = cleanup_orphaned_temp_files(folder, max_age_seconds=30)

    assert removed == []
    assert victim.exists()


def test_a_temp_file_that_vanishes_before_replace_fails_instead_of_being_rewritten(tmp_path, monkeypatch):
    # A concurrent orphan sweep only removes a temp file older than 30s;
    # failing here, not rewriting and retrying, is the documented answer
    # (cleanup_orphaned_temp_files's known limitation).
    target = tmp_path / "decision.md"
    target.write_text("original")
    calls = {"n": 0}

    def replace_after_temp_vanished(src, dst):
        calls["n"] += 1
        os.unlink(src)
        raise FileNotFoundError(2, "No such file or directory", str(src))

    monkeypatch.setattr("adrpy.core.fs.os.replace", replace_after_temp_vanished)
    monkeypatch.setattr("adrpy.core.fs.time.sleep", lambda _seconds: None)

    with pytest.raises(FileNotFoundError):
        atomic_write_text(target, "content")

    assert calls["n"] == 1
    assert target.read_text() == "original"


def test_a_chunk_source_that_disappears_fails_at_once(tmp_path, monkeypatch):
    target = tmp_path / "decision.md"
    calls = {"n": 0}

    def chunks():
        calls["n"] += 1
        raise FileNotFoundError(2, "No such file or directory", str(tmp_path / "source.md"))
        yield b""  # pragma: no cover

    monkeypatch.setattr("adrpy.core.fs.time.sleep", lambda _seconds: None)

    with pytest.raises(FileNotFoundError):
        atomic_write_chunks(target, chunks)

    assert calls["n"] == 1


def test_a_missing_destination_folder_still_fails_at_once(tmp_path):
    # Positive control: FileNotFoundError that retrying can't fix.
    with pytest.raises(FileNotFoundError):
        atomic_write_text(tmp_path / "no-such-folder" / "decision.md", "content")


def test_a_temp_file_that_vanished_before_the_sweep_reached_it_is_not_reported_as_stuck(tmp_path):
    from adrpy.core.fs import _remove_orphans

    warnings = []
    removed = _remove_orphans([tmp_path / f"gone.md.{OWN_TEMP_HEX}.tmp"], 30, warnings)

    assert removed == []
    assert warnings == []


def test_a_commit_retry_does_not_run_the_chunk_factory_again(tmp_path, monkeypatch):
    # The temp file is complete before the commit starts; retrying the
    # commit must reuse it, not stream the source a second time.
    target = tmp_path / "decision.md"
    calls = {"factory": 0, "replace": 0}
    real_replace = os.replace

    def chunks():
        calls["factory"] += 1
        yield b"content"

    def replace_fails_once(src, dst):
        calls["replace"] += 1
        if calls["replace"] == 1:
            raise PermissionError(13, "Access is denied", str(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", replace_fails_once)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)

    attempts = atomic_write_chunks(target, chunks)

    assert calls == {"factory": 1, "replace": 2}
    assert attempts == 2
    assert target.read_bytes() == b"content"


def test_cleanup_removes_an_orphan_with_the_short_suffix_prepare_write_now_uses(tmp_path):
    orphan = tmp_path / f"0001-decision.md.{OWN_TEMP_HEX[:16]}.tmp"
    orphan.write_text("stale")
    old_time = time.time() - 60
    os.utime(orphan, (old_time, old_time))

    removed = cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30)

    assert removed == [orphan]


@pytest.mark.parametrize("width", [15, 17, 31])
def test_cleanup_never_removes_a_tmp_file_with_a_hex_part_of_another_width(tmp_path, width):
    foreign = tmp_path / f"0001-decision.md.{(OWN_TEMP_HEX * 2)[:width]}.tmp"
    foreign.write_text("user data")
    old_time = time.time() - 60
    os.utime(foreign, (old_time, old_time))

    assert cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30) == []
    assert foreign.exists()


@pytest.mark.parametrize("name", ["notes.0123456789abcdef.tmp", "report.pdf.0123456789abcdef.tmp"])
def test_the_folder_sweep_never_removes_a_16_hex_tmp_that_is_not_a_decision_s(tmp_path, name):
    # Every file this tool writes in the decisions and decision-log folders
    # is a .md: a 16-hex temp of any other name is the user's.
    foreign = tmp_path / name
    foreign.write_text("user data")
    old_time = time.time() - 60
    os.utime(foreign, (old_time, old_time))

    assert cleanup_orphaned_temp_files(tmp_path, max_age_seconds=30) == []
    assert foreign.exists()


def test_the_named_files_sweep_removes_a_16_hex_orphan_of_its_file(tmp_path):
    from adrpy.core.fs import cleanup_orphaned_temp_files_for

    target = tmp_path / "adr-config.adrplus"
    orphan = tmp_path / f"adr-config.adrplus.{OWN_TEMP_HEX[:16]}.tmp"
    orphan.write_text("stale")
    old_time = time.time() - 60
    os.utime(orphan, (old_time, old_time))

    assert cleanup_orphaned_temp_files_for([target], max_age_seconds=30) == [orphan]
