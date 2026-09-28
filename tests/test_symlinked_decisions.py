"""A decision file that is a symbolic link: writing it would replace the link
with a regular file and leave the file it points to unchanged, while the
command reports success. Commands that rewrite a decision refuse one
(target-is-a-link), migrate reports it for that file, and check warns about
every link it finds in the decisions folder."""

import json
import os
from pathlib import Path

import pytest

from adrpy.cli import approve, check, init, migrate, new
from adrpy.core.errors import CommandError


def _symlink(link, target, target_is_directory=False):
    try:
        os.symlink(target, link, target_is_directory=target_is_directory)
    except OSError:
        pytest.skip("creating a symlink needs a privilege this host does not grant")


def _repo_with_a_linked_decision(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Alpha one", "--refdate", "2026-01-01"])
    adr = tmp_path / "doc" / "adr"
    real = adr / "ADR001V01-alpha-one.md"
    link = adr / "sub" / real.name
    link.parent.mkdir()
    _symlink(link, real)
    return real, link


def test_approve_through_a_symlinked_decision_is_refused_and_writes_nothing(tmp_path):
    real, link = _repo_with_a_linked_decision(tmp_path)
    before = real.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(link), "--refdate", "2026-01-02"])

    assert excinfo.value.code == "target-is-a-link"
    assert link.is_symlink()
    assert real.read_bytes() == before


def test_approve_of_the_real_file_next_to_a_link_still_works(tmp_path):
    real, link = _repo_with_a_linked_decision(tmp_path)

    result = approve.run(["--file", str(real), "--refdate", "2026-01-02"])

    assert result["status"] == "Accepted"
    assert link.is_symlink()


def test_check_warns_about_a_symlinked_decision(tmp_path):
    _real, link = _repo_with_a_linked_decision(tmp_path)

    result = check.run(["--path", str(tmp_path)])

    assert any(link.name in warning and "symbolic link" in warning for warning in result["warnings"])


def test_migrate_reports_a_symlinked_candidate_and_leaves_the_link(tmp_path):
    seed = json.loads((Path(__file__).parent / "fixtures" / "adr-config.adrplus").read_text(encoding="utf-8"))
    seed["migrationpattern"] = "N00:04T05"
    seed_file = tmp_path / "seed.json"
    seed_file.write_text(json.dumps(seed), encoding="utf-8")
    repo = tmp_path / "repo"
    repo.mkdir()
    init.run(["--path", str(repo), "--seed", str(seed_file)])
    adr = repo / "doc" / "adr"
    adr.mkdir(parents=True, exist_ok=True)
    (adr / "notes.txt").write_bytes(b"# Notes\n")
    link = adr / "0012-notes-link.md"
    _symlink(link, adr / "notes.txt")
    (adr / "0001-real.md").write_bytes(b"# Real\n")

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(repo)])

    results = {Path(r["file"]).name: r for r in excinfo.value.data["results"]}
    assert results["0001-real.md"]["status"] == "migrated"
    assert results[link.name]["status"] == "failed" and "symbolic link" in results[link.name]["error"]
    assert link.is_symlink()
    assert (adr / "notes.txt").read_bytes() == b"# Notes\n"


@pytest.mark.skipif(os.name == "nt", reason="Windows collapses `..` before following a link: no path can differ")
def test_a_file_path_with_dot_dot_after_a_symlinked_folder_says_it_is_read_as_written(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    init.run(["--path", str(repo)])
    new.run(["--path", str(repo), "--title", "Alpha one", "--refdate", "2026-01-01"])
    out = tmp_path / "out"
    out.mkdir()
    _symlink(out / "link", repo / "doc", target_is_directory=True)
    through = out / "link" / ".." / "doc" / "adr" / "ADR001V01-alpha-one.md"
    assert through.is_file()  # the OS follows the link, then `..`

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(through), "--refdate", "2026-01-02"])

    assert excinfo.value.code == "cannot-determine-root-path"
    assert "read as written" in excinfo.value.detail


@pytest.mark.parametrize(("command", "listed"), [("approve", True), ("reject", True), ("undo", True), ("supersede", True), ("version", False), ("revise", False)])
def test_only_the_commands_that_rewrite_their_file_document_target_is_a_link(command, listed):
    from adrpy.core.registry import COMMANDS

    codes = [entry["code"] for entry in COMMANDS[command].describe()["failure_codes"]]
    assert ("target-is-a-link" in codes) is listed


@pytest.mark.skipif(os.name == "nt", reason="Windows collapses `..` before following a link: no path can differ")
def test_a_dot_dot_before_a_symlinked_folder_is_not_blamed_on_the_link(tmp_path):
    # `out/zzz/../link/...` means the same file read literally or by the OS:
    # the missing repository is the only problem, and the message says only that.
    noconfig = tmp_path / "noconfig" / "doc" / "adr"
    noconfig.mkdir(parents=True)
    (noconfig / "ADR001V01-a.md").write_bytes(b"x")
    out = tmp_path / "out"
    (out / "zzz").mkdir(parents=True)
    _symlink(out / "link", tmp_path / "noconfig", target_is_directory=True)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(out / "zzz" / ".." / "link" / "doc" / "adr" / "ADR001V01-a.md"), "--refdate", "2026-01-02"])

    assert excinfo.value.code == "cannot-determine-root-path"
    assert "read as written" not in excinfo.value.detail


def test_check_warns_about_a_symlinked_decision_that_points_outside_the_folder(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Alpha one", "--refdate", "2026-01-01"])
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"x")
    link = tmp_path / "doc" / "adr" / "ADR003V01-out.md"
    _symlink(link, outside)

    result = check.run(["--path", str(tmp_path)])

    assert any(link.name in warning for warning in result["warnings"])
