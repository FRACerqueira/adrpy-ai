"""Every failure raised once the target file has been read carries the
warnings already accumulated for it -- including the checks that run
before the decisions folder is resolved (revise's revision-not-configured)
and the folder resolution itself."""

import subprocess
import sys

import pytest

from adrpy.cli import approve, init, new, revise
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.atomic_write import atomic_write_text


def _repo_with_mismatched_label(tmp_path):
    """A fresh repository (lenrevision 0) with one Proposed decision whose
    visible Created label was hand-edited to disagree with its marker."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    text = adr_path.read_text(encoding="utf-8")
    atomic_write_text(adr_path, text.replace(config.statusnew, config.statusacc, 1))
    return adr_path


def test_revision_not_configured_carries_the_marker_label_warning(tmp_path):
    adr_path = _repo_with_mismatched_label(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    assert excinfo.value.code == "revision-not-configured"
    assert any("marker" in w for w in (excinfo.value.warnings or []))


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_a_decisions_folder_escaping_the_repository_is_refused_before_the_target_is_read(tmp_path):
    """folderadr is a junction to a directory outside the repository, and
    the target sits at the repository root: resolving the decisions
    folder fails before the target's own header is read, so no warning
    about that header can exist yet."""
    repo = tmp_path / "repo"
    repo.mkdir()
    adr_path = _repo_with_mismatched_label(repo)
    moved = repo / adr_path.name
    adr_path.replace(moved)
    folder = repo / "doc" / "adr"
    folder.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(folder), str(outside)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(moved), "--refdate", "2026-01-02"])

    assert excinfo.value.code == "path-outside-repository"
    assert excinfo.value.warnings == []
