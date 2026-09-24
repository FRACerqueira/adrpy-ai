"""supersede and reject of a successor write two files. Both are
prepared (complete temp files) before either is committed, then
committed in a fixed order. A failure while preparing leaves nothing
written and no temp file; a failure after the first commit is reported as
multi-file-write-partially-applied, naming what was written and what was
not."""

from pathlib import Path

import pytest

from adrpy.cli import approve, init, new, reject, supersede
from adrpy.core import fs, lifecycle
from adrpy.core.errors import CommandError


def _accepted(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    approve.run(["--file", str(path), "--refdate", "2026-01-02"])
    return path


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


def _fail_nth_prepare(monkeypatch, n):
    """Fails the n-th prepare_write of the command, wherever it is called
    from (supersede prepares its successor itself, lifecycle every
    rewrite)."""
    real_prepare = fs.prepare_write
    calls = {"n": 0}

    def failing_prepare(path, data):
        calls["n"] += 1
        if calls["n"] == n:
            raise OSError("simulated disk full")
        return real_prepare(path, data)

    monkeypatch.setattr(lifecycle, "prepare_write", failing_prepare)
    monkeypatch.setattr(supersede, "prepare_write", failing_prepare)


def _fail_nth_commit(monkeypatch, n):
    real_commit = lifecycle.commit_write
    calls = {"n": 0}

    def failing_commit(prepared, exclusive=False):
        calls["n"] += 1
        if calls["n"] == n:
            raise OSError("simulated disk failure")
        return real_commit(prepared, exclusive=exclusive)

    monkeypatch.setattr(lifecycle, "commit_write", failing_commit)


@pytest.mark.parametrize("n", [1, 2])
def test_supersede_failing_to_prepare_either_file_writes_nothing(tmp_path, monkeypatch, n):
    path = _accepted(tmp_path)
    folder = path.parent
    before = _snapshot(folder)
    _fail_nth_prepare(monkeypatch, n)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-write-failed"
    assert excinfo.value.data == {"intended_successor": str(folder / "ADR002V01-first-decision--001.md")}
    assert _snapshot(folder) == before


def test_supersede_failing_after_the_successor_names_what_was_written(tmp_path, monkeypatch):
    path = _accepted(tmp_path)
    before = path.read_bytes()
    successor = path.parent / "ADR002V01-first-decision--001.md"
    _fail_nth_commit(monkeypatch, 2)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "multi-file-write-partially-applied"
    assert {k: v for k, v in excinfo.value.data.items() if k != "repair"} == {"applied": [str(successor)], "pending": [str(path)]}
    assert set(excinfo.value.data["repair"]) == {"file", "row"}
    assert successor.exists()
    assert path.read_bytes() == before
    assert list(path.parent.glob("*.tmp")) == []


def _superseded(tmp_path):
    path = _accepted(tmp_path)
    successor = Path(supersede.run(["--file", str(path), "--refdate", "2026-01-05"])["created"])
    return path, successor


@pytest.mark.parametrize("n", [1, 2])
def test_reject_of_a_successor_failing_to_prepare_either_file_writes_nothing(tmp_path, monkeypatch, n):
    path, successor = _superseded(tmp_path)
    before = _snapshot(path.parent)
    _fail_nth_prepare(monkeypatch, n)

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "reject-predecessor-write-failed"
    assert _snapshot(path.parent) == before


def test_reject_of_a_successor_failing_after_the_revert_names_what_was_written(tmp_path, monkeypatch):
    path, successor = _superseded(tmp_path)
    successor_before = successor.read_bytes()
    _fail_nth_commit(monkeypatch, 2)

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "multi-file-write-partially-applied"
    assert {k: v for k, v in excinfo.value.data.items() if k != "repair"} == {"applied": [str(path)], "pending": [str(successor)]}
    assert set(excinfo.value.data["repair"]) == {"file", "row"}
    assert "|Superseded||" in path.read_text(encoding="utf-8")
    assert successor.read_bytes() == successor_before
    assert list(path.parent.glob("*.tmp")) == []


def _interrupt_nth_commit(monkeypatch, n):
    real_commit = lifecycle.commit_write
    calls = {"n": 0}

    def interrupted_commit(prepared, exclusive=False):
        calls["n"] += 1
        if calls["n"] == n:
            raise KeyboardInterrupt()
        return real_commit(prepared, exclusive=exclusive)

    monkeypatch.setattr(lifecycle, "commit_write", interrupted_commit)


def test_supersede_interrupted_after_the_successor_names_what_was_written(tmp_path, monkeypatch, capsys):
    # Ctrl+C between the two commits: the successor is on disk, so the
    # answer must say so, like a write failure at the same point does.
    import json

    from adrpy.__main__ import main

    path = _accepted(tmp_path)
    successor = path.parent / "ADR002V01-first-decision--001.md"
    _interrupt_nth_commit(monkeypatch, 2)
    capsys.readouterr()

    main(["supersede", "--file", str(path), "--refdate", "2026-01-05"])

    response = json.loads(capsys.readouterr().out)
    assert response["code"] == "interrupted"
    assert response["data"]["applied"] == [str(successor)]
    assert response["data"]["pending"] == [str(path)]
    assert set(response["data"]["repair"]) == {"file", "row"}
    assert "warnings" in response
    assert successor.exists()
    assert list(path.parent.glob("*.tmp")) == []


def test_reject_interrupted_after_the_revert_names_what_was_written(tmp_path, monkeypatch):
    path, successor = _superseded(tmp_path)
    _interrupt_nth_commit(monkeypatch, 2)

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "interrupted"
    assert {k: v for k, v in excinfo.value.data.items() if k != "repair"} == {"applied": [str(path)], "pending": [str(successor)]}
    assert list(path.parent.glob("*.tmp")) == []


def test_an_interrupt_before_any_commit_still_propagates_with_nothing_written(tmp_path, monkeypatch):
    path = _accepted(tmp_path)
    before = _snapshot(path.parent)
    _interrupt_nth_commit(monkeypatch, 1)

    with pytest.raises(KeyboardInterrupt):
        supersede.run(["--file", str(path), "--refdate", "2026-01-05"])

    assert _snapshot(path.parent) == before
