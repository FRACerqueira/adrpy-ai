import ast
import errno
import os
import subprocess
import sys
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
    # still exclusive (an O_EXCL reservation) and atomic (os.replace onto it).
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


class _Crash(BaseException):
    """Stands in for the process dying (not KeyboardInterrupt, which would
    stop the whole test session if it escaped)."""


def _no_hard_links(monkeypatch):
    monkeypatch.setattr(fs, "_IS_WINDOWS", False)

    def no_links(_src, _dst):
        raise OSError(errno.EPERM, os.strerror(errno.EPERM))

    monkeypatch.setattr(os, "link", no_links)


def test_a_crash_in_the_no_hard_link_fallback_never_leaves_a_partial_decision(tmp_path, monkeypatch):
    # A killed process runs no cleanup, so _discard does nothing here. The
    # crash can come at any point of the fallback: while the content is
    # read into the target, or right before the complete temp is moved
    # onto it. Either way the target may only be absent or empty (an empty
    # file fails the validator as no-header), never a truncated decision.
    _no_hard_links(monkeypatch)
    monkeypatch.setattr(fs, "_discard", lambda _path: None)
    target = tmp_path / "decision.md"
    content = b"x" * (3 * (1 << 16) + 7)
    prepared = fs.prepare_write(target, content)

    real_open, real_replace = open, os.replace

    def crashing_open(path, mode="r", *args, **kwargs):
        handle = real_open(path, mode, *args, **kwargs)
        if "r" in mode and Path(path) == prepared.temp_path:
            first = handle.read

            def read_once(size=-1, _calls=[]):
                _calls.append(1)
                if len(_calls) > 1:
                    raise _Crash()
                return first(size)

            handle.read = read_once
        return handle

    def crashing_replace(src, dst):
        if Path(dst) == target:
            raise _Crash()
        return real_replace(src, dst)

    monkeypatch.setattr(fs, "open", crashing_open, raising=False)
    monkeypatch.setattr(os, "replace", crashing_replace)

    with pytest.raises(_Crash):
        fs.commit_write(prepared, exclusive=True)

    assert target.read_bytes() == b""
    assert prepared.temp_path.read_bytes() == content


def test_the_no_hard_link_fallback_retries_a_transient_permission_error(tmp_path, monkeypatch):
    # The retry runs the whole fallback again: its own reservation from the
    # failed attempt must not be taken for someone else's file.
    _no_hard_links(monkeypatch)
    real_replace = os.replace
    calls = []

    def busy_once(src, dst):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(errno.EACCES, "busy")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", busy_once)
    target = tmp_path / "decision.md"

    assert fs.commit_write(fs.prepare_write(target, b"new"), exclusive=True) == 2

    assert target.read_bytes() == b"new"
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


def test_scan_tree_collects_markdown_and_temp_files_recursively(tmp_path):
    (tmp_path / "sub" / "deeper").mkdir(parents=True)
    for name in ("a.md", "sub/b.md", "sub/deeper/c.md", "sub/x.md.0123.tmp", "notes.txt", "sub/image.png"):
        (tmp_path / name).write_bytes(b"x")

    scan = fs.scan_tree(tmp_path)

    assert sorted(p.relative_to(tmp_path).as_posix() for p in scan.markdown) == ["a.md", "sub/b.md", "sub/deeper/c.md"]
    assert [p.name for p in scan.temp] == ["x.md.0123.tmp"]
    assert (scan.excluded, scan.unreadable) == ((), ())


def test_scan_tree_reports_a_directory_it_cannot_list(tmp_path, monkeypatch):
    blocked = tmp_path / "restricted"
    blocked.mkdir()
    (tmp_path / "a.md").write_bytes(b"x")
    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    scan = fs.scan_tree(tmp_path)

    assert [p.name for p in scan.markdown] == ["a.md"]
    assert scan.unreadable == (str(blocked),)


def test_scan_tree_reports_a_missing_folder_as_unreadable(tmp_path):
    assert fs.scan_tree(tmp_path / "missing").unreadable == (str(tmp_path / "missing"),)


def test_scan_tree_excludes_a_file_whose_real_path_escapes_the_folder(tmp_path):
    inside, outside = tmp_path / "inside", tmp_path / "outside"
    inside.mkdir()
    outside.mkdir()
    (outside / "victim.md").write_bytes(b"x")
    try:
        (inside / "link.md").symlink_to(outside / "victim.md")
    except OSError:
        pytest.skip("creating a symlink needs a privilege this host does not grant")

    scan = fs.scan_tree(inside)

    assert (scan.markdown, [p.name for p in scan.excluded]) == ((), ["link.md"])


def _junction(link, target):
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def _resolve_everything(folder):
    """The reference rule scan_tree must keep: os.walk, then every .md
    resolved and kept only inside the resolved folder, once per real
    path (the path that needs no link wins)."""
    resolved = Path(folder).resolve()
    found, excluded = {}, []
    for dirpath, _dirnames, filenames in os.walk(folder):
        for name in filenames:
            if not name.endswith(".md"):
                continue
            candidate = Path(dirpath) / name
            real = candidate.resolve()
            if not real.is_relative_to(resolved):
                excluded.append(candidate)
                continue
            if real not in found or str(candidate.relative_to(folder)) == str(real.relative_to(resolved)):
                found[real] = candidate
    return sorted(found.values()), sorted(excluded)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_scan_tree_matches_the_resolve_everything_rule_through_junctions(tmp_path):
    """A junction to outside the folder: excluded, not entered. A
    junction to a directory inside it: each file is kept once, under the
    path with no link. Plain directories around them: kept as they are."""
    folder, outside = tmp_path / "adr", tmp_path / "outside"
    (folder / "team" / "deep").mkdir(parents=True)
    outside.mkdir()
    for name in ("a.md", "team/b.md", "team/deep/c.md"):
        (folder / name).write_bytes(b"x")
    (outside / "victim.md").write_bytes(b"x")
    _junction(folder / "escape", outside)
    _junction(folder / "alias", folder / "team")

    scan = fs.scan_tree(folder)

    assert sorted(scan.markdown) == _resolve_everything(folder)[0]
    assert sorted(p.relative_to(folder).as_posix() for p in scan.markdown) == ["a.md", "team/b.md", "team/deep/c.md"]
    # The junction out of the folder is excluded as a whole, not entered.
    assert [p.relative_to(folder).as_posix() for p in scan.excluded] == ["escape"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
@pytest.mark.parametrize("target", ["folder-itself", "outside-ancestor"])
def test_scan_tree_never_loops_through_a_junction_cycle(tmp_path, monkeypatch, target):
    """A junction back to the folder itself, or to an ancestor outside it,
    used to make the walk exponential (seconds to minutes): a directory
    whose real path was already listed is not listed again, and one whose
    real path is outside the folder is excluded without being entered."""
    folder = tmp_path / "repo" / "adr"
    (folder / "team").mkdir(parents=True)
    (folder / "a.md").write_bytes(b"x")
    (folder / "team" / "b.md").write_bytes(b"x")
    _junction(folder / "team" / "loop", folder if target == "folder-itself" else tmp_path)
    real_scandir = os.scandir
    calls = []

    def capped_scandir(path):
        calls.append(path)
        if len(calls) > 50:
            raise RuntimeError("the walk is looping")
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", capped_scandir)

    scan = fs.scan_tree(folder)

    assert sorted(p.relative_to(folder).as_posix() for p in scan.markdown) == ["a.md", "team/b.md"]
    assert len(calls) <= 3


def test_scan_tree_keeps_a_symlinked_file_inside_the_folder_once(tmp_path):
    (tmp_path / "a.md").write_bytes(b"x")
    try:
        (tmp_path / "link.md").symlink_to(tmp_path / "a.md")
    except OSError:
        pytest.skip("creating a symlink needs a privilege this host does not grant")

    scan = fs.scan_tree(tmp_path)

    assert ([p.name for p in scan.markdown], scan.excluded) == (["a.md"], ())


def test_scan_tree_resolves_only_the_folder_when_nothing_is_a_link(tmp_path, monkeypatch):
    """The per-file resolve() was ~96% of the scan's cost: a file reached
    through plain directories is inside by construction, so only the
    folder itself is resolved."""
    for index in range(20):
        (tmp_path / f"sub{index % 3}").mkdir(exist_ok=True)
        (tmp_path / f"sub{index % 3}" / f"d{index}.md").write_bytes(b"x")
    real_resolve = Path.resolve
    calls = []

    def counting_resolve(self, *args, **kwargs):
        calls.append(self)
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting_resolve)

    scan = fs.scan_tree(tmp_path)

    assert len(scan.markdown) == 20
    assert calls == [tmp_path]


def _count_rglob(monkeypatch):
    calls = []
    real_rglob = Path.rglob

    def counting_rglob(self, *args, **kwargs):
        calls.append(self)
        return real_rglob(self, *args, **kwargs)

    monkeypatch.setattr(Path, "rglob", counting_rglob)
    return calls


def test_the_orphan_sweep_reuses_the_command_scan_instead_of_walking_again(tmp_path, monkeypatch):
    """approve (through prepare()), new and migrate sweep orphaned temp
    files from the scan they already took -- no second walk (rglob)."""
    from adrpy.cli import approve, migrate, new

    from conftest import D, make_repo

    repo = make_repo(tmp_path / "a", files=[D(1)])
    legacy = make_repo(tmp_path / "m", config={"migrationpattern": "N00:04T04"})
    (legacy.folder / "0001T01.md").write_bytes(b"Legacy content\n")
    calls = _count_rglob(monkeypatch)

    approve.run(["--file", str(repo.paths[0])])
    new.run(["--path", str(repo.root), "--title", "Second"])
    migrate.run(["--path", str(legacy.root)])

    assert calls == []


def test_a_reservation_that_cannot_be_removed_is_not_taken_for_someone_elses_file(tmp_path, monkeypatch):
    # The fallback's replace keeps failing with a PermissionError and its
    # own empty reservation cannot be removed: a retry would then find
    # that reservation and answer "file already exists" about a file this
    # very call created. It fails once, with an error naming it instead.
    _no_hard_links(monkeypatch)
    target = tmp_path / "decision.md"

    def always_busy(_src, _dst):
        raise PermissionError(errno.EACCES, "busy")

    real_unlink = Path.unlink

    def stuck_reservation(self, missing_ok=False):
        if self == target:
            raise PermissionError(errno.EACCES, "in use")
        return real_unlink(self, missing_ok=missing_ok)

    monkeypatch.setattr(os, "replace", always_busy)
    monkeypatch.setattr(Path, "unlink", stuck_reservation)

    with pytest.raises(OSError) as excinfo:
        fs.commit_write(fs.prepare_write(target, b"new"), exclusive=True)

    assert not isinstance(excinfo.value, (FileExistsError, PermissionError))
    assert excinfo.value.filename == str(target)
    assert target.read_bytes() == b""
    assert _temps(tmp_path) == []


def test_prepare_write_names_its_temp_with_a_16_hex_suffix(tmp_path):
    target = tmp_path / "x.md"

    prepared = fs.prepare_write(target, b"data")
    try:
        suffix = prepared.temp_path.name[len(target.name):]
        assert len(suffix) == 21
        assert suffix.startswith(".") and suffix.endswith(".tmp")
        assert all(char in "0123456789abcdef" for char in suffix[1:-4])
    finally:
        fs.discard_write(prepared)
