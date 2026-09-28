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


def test_revision_not_configured_names_the_command_that_turns_revisions_on(tmp_path):
    adr_path = _repo_with_mismatched_label(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    from adrpy.core.text import shell_argument

    assert f"adrpy config --path {shell_argument(tmp_path)} --lenrevision" in excinfo.value.detail


@pytest.mark.parametrize(
    ("cwd", "relative"),
    [
        (("doc", "adr"), "ADR001V01-first-decision.md"),
        (("doc", "adr"), "./ADR001V01-first-decision.md"),
        (("doc", "adr"), "../adr/ADR001V01-first-decision.md"),
        (("doc",), "adr/ADR001V01-first-decision.md"),
    ],
)
def test_a_file_given_relative_to_the_current_directory_finds_its_repository(tmp_path, monkeypatch, cwd, relative):
    # The walk up for adr-config.adrplus starts from the file's real
    # folder, not from the relative path's own parent ('.', whose parent
    # is '.').
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    monkeypatch.chdir(tmp_path.joinpath(*cwd))

    result = approve.run(["--file", relative, "--refdate", "2026-01-02"])

    assert result["status"] == "Accepted"


def test_a_relative_file_through_dot_dot_is_not_given_the_current_directory_s_repository(tmp_path, monkeypatch):
    # From repository A, `--file ../B/...` names a folder with no config
    # anywhere above it: the walk goes up from the file's real folder, not
    # through A (the unresolved path's parents include A itself).
    repo_a = tmp_path / "A"
    repo_a.mkdir()
    init.run(["--path", str(repo_a)])
    new.run(["--path", str(repo_a), "--title", "First decision", "--refdate", "2026-01-01"])
    other = tmp_path / "B" / "doc" / "adr"
    other.mkdir(parents=True)
    source = repo_a / "doc" / "adr" / "ADR001V01-first-decision.md"
    (other / source.name).write_bytes(source.read_bytes())
    monkeypatch.chdir(repo_a)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", f"../B/doc/adr/{source.name}", "--refdate", "2026-01-02"])

    assert excinfo.value.code == "cannot-determine-root-path"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_a_file_reached_through_a_junction_to_another_repository_is_not_acted_on(tmp_path):
    # The walk up normalizes `..` but follows no link: a junction inside A
    # to B's decisions folder does not make a path under A act on B.
    repo_b = tmp_path / "B"
    repo_b.mkdir()
    init.run(["--path", str(repo_b)])
    new.run(["--path", str(repo_b), "--title", "In B", "--refdate", "2026-01-01"])
    repo_a = tmp_path / "A"
    repo_a.mkdir()
    init.run(["--path", str(repo_a)])
    shared = repo_a / "doc" / "adr" / "shared"
    result = subprocess.run(["cmd", "/c", "mklink", "/J", str(shared), str(repo_b / "doc" / "adr")], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    target_in_b = repo_b / "doc" / "adr" / "ADR001V01-in-b.md"
    before = target_in_b.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(shared / target_in_b.name), "--refdate", "2026-01-02"])

    assert excinfo.value.code == "target-outside-folderadr"
    assert target_in_b.read_bytes() == before


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
