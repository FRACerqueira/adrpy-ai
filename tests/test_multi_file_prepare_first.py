"""supersede and reject of a successor prepare every file before
committing any: a file whose body cannot be read (the second file each
command writes) fails the command with nothing written. The seam is
lifecycle.stream_normalized_body_chunks, the body read of every
rewrite."""

import pytest

from adrpy.cli import approve, init, new, reject, supersede
from adrpy.core import lifecycle
from adrpy.core.errors import CommandError


def _accepted(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    approve.run(["--file", str(path), "--refdate", "2026-01-02"])
    return path


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir()) if p.is_file()}


def _unreadable_body(monkeypatch, source):
    real_stream = lifecycle.stream_normalized_body_chunks

    def stream(source_path, report):
        if source_path == source:
            raise OSError("simulated unreadable body")
        yield from real_stream(source_path, report)

    monkeypatch.setattr(lifecycle, "stream_normalized_body_chunks", stream)


def test_supersede_with_an_unreadable_predecessor_body_writes_nothing(tmp_path, monkeypatch):
    path = _accepted(tmp_path)
    before = _snapshot(path.parent)
    _unreadable_body(monkeypatch, path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-write-failed"
    assert _snapshot(path.parent) == before


def test_reject_of_a_successor_with_an_unreadable_own_body_writes_nothing(tmp_path, monkeypatch):
    path = _accepted(tmp_path)
    successor = path.parent / supersede.run(["--file", str(path), "--refdate", "2026-01-05"])["created"]
    before = _snapshot(path.parent)
    _unreadable_body(monkeypatch, successor)

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "reject-predecessor-write-failed"
    assert _snapshot(path.parent) == before
