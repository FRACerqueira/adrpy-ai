import ast
import errno
import os
import time
from pathlib import Path

import pytest

import adrpy
from adrpy.core import fs

SRC = Path(adrpy.__file__).parent

_BANNED_METHODS = {"read_bytes", "read_text", "write_bytes", "write_text", "unlink"}
_BANNED_OS = {"replace", "remove", "unlink", "rename", "link"}

# Package resources loaded through importlib.resources, not files on disk
# the tool writes: (file relative to src/adrpy, receiver name, method).
_ALLOWED = {
    ("core/config.py", "resource", "read_text"),
    ("skills/resources.py", "ref", "read_text"),
}


def _direct_io(path, root=SRC):
    relative = path.relative_to(root).as_posix()
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Attribute):
            continue
        receiver = node.value.id if isinstance(node.value, ast.Name) else None
        if receiver == "os" and node.attr in _BANNED_OS:
            found.append(f"{relative}:{node.lineno} os.{node.attr}")
        elif node.attr in _BANNED_METHODS and (relative, receiver, node.attr) not in _ALLOWED:
            found.append(f"{relative}:{node.lineno} .{node.attr}")
    return found


def test_only_core_fs_does_file_io_directly():
    """Every read, write and delete goes through core/fs.py, so the
    retry, the bounded read and the temp-then-commit write live in one
    place. An attribute reference counts as well as a call: passing
    `path.read_bytes` uncalled to a retry helper is still a direct read."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        if path.relative_to(SRC).as_posix() != "core/fs.py":
            offenders.extend(_direct_io(path))
    assert offenders == []


def test_the_source_scan_catches_what_it_forbids(tmp_path):
    # Positive control: without this, an AST walk that matched nothing
    # would pass the test above vacuously.
    sample = tmp_path / "core" / "sample.py"
    sample.parent.mkdir()
    sample.write_text(
        "import os\n"
        "def f(path, resource):\n"
        "    os.replace(path, path)\n"
        "    retry(path.read_bytes)\n"
        "    path.unlink()\n"
        "    resource.read_text()\n",
        encoding="utf-8",
    )
    assert _direct_io(sample, root=tmp_path) == [
        "core/sample.py:3 os.replace",
        "core/sample.py:4 .read_bytes",
        "core/sample.py:5 .unlink",
        "core/sample.py:6 .read_text",
    ]


# -- retry_on_permission -------------------------------------------------


def _fails(times, error=PermissionError):
    calls = {"n": 0}

    def fn():
        calls["n"] += 1
        if calls["n"] <= times:
            raise error(13, "Access is denied")
        return "ok"

    return fn, calls


def test_retry_returns_the_result_and_the_calls_made(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    fn, calls = _fails(2)

    assert fs.retry_on_permission(fn, attempts=5, delay=0.05, exponential=True) == ("ok", 3)
    assert sleeps == [0.05, 0.1]


def test_retry_spends_exactly_the_attempts_given_then_reraises(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    fn, calls = _fails(10)

    with pytest.raises(PermissionError):
        fs.retry_on_permission(fn, attempts=fs.RETRY_ATTEMPTS, delay=fs.RETRY_DELAY_SECONDS, exponential=True)

    assert calls["n"] == 5
    # No sleep after the last attempt.
    assert sleeps == [0.05, 0.1, 0.2, 0.4]


def test_the_read_side_keeps_its_flat_three_attempt_budget(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    fn, calls = _fails(10)

    with pytest.raises(PermissionError):
        fs.read_with_permission_retry(fn)

    assert calls["n"] == 3
    assert sleeps == [0.05, 0.05]


def test_retry_never_retries_another_oserror(monkeypatch):
    monkeypatch.setattr(time, "sleep", lambda _s: None)
    fn, calls = _fails(10, error=FileNotFoundError)

    with pytest.raises(FileNotFoundError):
        fs.retry_on_permission(fn, attempts=5, delay=0)

    assert calls["n"] == 1


def test_unlink_with_retry_uses_the_write_side_budget(tmp_path, monkeypatch):
    target = tmp_path / "gone.md"
    target.write_text("x")
    sleeps = []
    monkeypatch.setattr(time, "sleep", sleeps.append)
    real_unlink = Path.unlink
    calls = {"n": 0}

    def flaky_unlink(self, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] < 5:
            raise PermissionError(13, "Access is denied")
        return real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", flaky_unlink)

    fs.unlink_with_retry(target)

    assert not target.exists()
    assert sleeps == [0.05, 0.1, 0.2, 0.4]


def test_read_bounded_stops_one_chunk_past_the_limit(tmp_path):
    big = tmp_path / "big.bin"
    big.write_bytes(b"x" * 1000)

    assert len(fs.read_bounded(big, 100, 10)) == 110
    assert fs.read_bounded(big, 5000, 64) == b"x" * 1000


# -- prepare_write / commit_write ---------------------------------------


def _temps(folder):
    return [p.name for p in folder.glob("*.tmp")]


def test_prepare_writes_the_whole_temp_and_leaves_the_target_alone(tmp_path):
    target = tmp_path / "decision.md"
    target.write_bytes(b"old")

    prepared = fs.prepare_write(target, lambda: iter([b"new ", b"content"]))

    assert target.read_bytes() == b"old"
    assert prepared.temp_path.read_bytes() == b"new content"
    fs.discard_write(prepared)
    assert _temps(tmp_path) == []


def test_a_failing_prepare_leaves_no_temp_and_no_target(tmp_path):
    target = tmp_path / "decision.md"

    def chunks():
        yield b"partial"
        raise OSError("disk full")

    with pytest.raises(OSError, match="disk full"):
        fs.prepare_write(target, chunks)

    assert not target.exists()
    assert _temps(tmp_path) == []


def test_commit_replaces_an_existing_target_by_default(tmp_path):
    target = tmp_path / "decision.md"
    target.write_bytes(b"old")

    assert fs.commit_write(fs.prepare_write(target, b"new")) == 1

    assert target.read_bytes() == b"new"
    assert _temps(tmp_path) == []


@pytest.fixture(params=["windows-rename", "posix-link"])
def exclusive_branch(request, monkeypatch):
    if request.param == "windows-rename":
        if not fs._IS_WINDOWS:
            pytest.skip("POSIX os.rename replaces an existing target; this branch needs Windows")
        monkeypatch.setattr(fs, "_IS_WINDOWS", True)
    else:
        monkeypatch.setattr(fs, "_IS_WINDOWS", False)
    return request.param


def test_exclusive_commit_creates_a_free_name(tmp_path, exclusive_branch):
    target = tmp_path / "decision.md"

    assert fs.commit_write(fs.prepare_write(target, b"new"), exclusive=True) == 1

    assert target.read_bytes() == b"new"
    assert _temps(tmp_path) == []


def test_exclusive_commit_refuses_an_existing_name_and_keeps_it(tmp_path, exclusive_branch):
    target = tmp_path / "decision.md"
    target.write_bytes(b"theirs")

    with pytest.raises(FileExistsError):
        fs.commit_write(fs.prepare_write(target, b"mine"), exclusive=True)

    assert target.read_bytes() == b"theirs"
    assert _temps(tmp_path) == []


@pytest.mark.skipif(os.name == "nt", reason="creating a symlink needs privileges on Windows")
def test_exclusive_commit_refuses_a_dangling_symlink_instead_of_writing_through_it(tmp_path, exclusive_branch):
    target = tmp_path / "decision.md"
    outside = tmp_path / "outside" / "victim.md"
    target.symlink_to(outside)

    with pytest.raises(FileExistsError):
        fs.commit_write(fs.prepare_write(target, b"mine"), exclusive=True)

    assert target.is_symlink()
    assert not outside.exists()


@pytest.mark.parametrize("err", [errno.EPERM, errno.EOPNOTSUPP])
def test_exclusive_commit_falls_back_to_o_excl_where_hard_links_are_unsupported(tmp_path, monkeypatch, err):
    # exFAT, FAT and some network shares refuse hard links; the create is
    # still exclusive through O_EXCL, only no longer atomic.
    monkeypatch.setattr(fs, "_IS_WINDOWS", False)
    calls = []

    def no_links(_src, _dst):
        calls.append(1)
        raise OSError(err, os.strerror(err))

    monkeypatch.setattr(os, "link", no_links)
    target = tmp_path / "decision.md"

    fs.commit_write(fs.prepare_write(target, b"new"), exclusive=True)

    assert target.read_bytes() == b"new"
    assert _temps(tmp_path) == []
    assert calls == [1]

    target.write_bytes(b"theirs")
    with pytest.raises(FileExistsError):
        fs.commit_write(fs.prepare_write(target, b"mine"), exclusive=True)
    assert target.read_bytes() == b"theirs"
    assert _temps(tmp_path) == []


def test_a_failing_commit_removes_its_temp_and_keeps_the_target(tmp_path, monkeypatch):
    target = tmp_path / "decision.md"
    target.write_bytes(b"old")
    prepared = fs.prepare_write(target, b"new")

    def boom(_src, _dst):
        raise OSError("disk gone")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk gone"):
        fs.commit_write(prepared)

    assert target.read_bytes() == b"old"
    assert _temps(tmp_path) == []
