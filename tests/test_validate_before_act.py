"""Every command that acts on decisions validates the whole repository
first (core/consistency.validate_repository): an inconsistent one is
refused with repository-inconsistent and every broken rule in
data.errors, before anything is written."""

import os
import time

import pytest

from adrpy.cli import approve, migrate, new, reject, revise, supersede, undo, version
from adrpy.core.errors import CommandError, FailureCodes

from conftest import D, make_repo

# Two files with the same number, version and revision (different titles):
# something no command writes, invisible to every per-family guard.
_DUPLICATE = [D(5, title="Five A", state="accepted"), D(5, title="Five B", state="accepted")]

_FILE_COMMANDS = [
    (approve, D(1), {}),
    (reject, D(1), {}),
    (undo, D(1, state="accepted"), {}),
    (version, D(1, state="accepted"), {}),
    (revise, D(1, state="accepted"), {"lenrevision": 2}),
    (supersede, D(1, state="accepted"), {}),
]


def _snapshot(folder):
    return {path.name: path.read_bytes() for path in folder.rglob("*") if path.is_file()}


@pytest.mark.parametrize(
    "command, target, config", _FILE_COMMANDS, ids=[entry[0].__name__.rsplit(".", 1)[-1] for entry in _FILE_COMMANDS]
)
def test_a_file_command_refuses_an_inconsistent_repository(tmp_path, command, target, config):
    repo = make_repo(tmp_path, config=config, files=[target, *_DUPLICATE])
    before = _snapshot(repo.folder)

    with pytest.raises(CommandError) as caught:
        command.run(["--file", str(repo.paths[0])])

    assert caught.value.code == FailureCodes.REPOSITORY_INCONSISTENT
    errors = caught.value.data["errors"]
    assert [error["code"] for error in errors] == [FailureCodes.DUPLICATE_NUMBER]
    assert {errors[0]["file"], *errors[0]["related_files"]} == {str(path) for path in repo.paths[1:]}
    assert _snapshot(repo.folder) == before


def test_new_refuses_an_inconsistent_repository(tmp_path):
    repo = make_repo(tmp_path, files=_DUPLICATE)
    before = _snapshot(repo.folder)

    with pytest.raises(CommandError) as caught:
        new.run(["--path", str(repo.root), "--title", "Another"])

    assert caught.value.code == FailureCodes.REPOSITORY_INCONSISTENT
    assert [error["code"] for error in caught.value.data["errors"]] == [FailureCodes.DUPLICATE_NUMBER]
    assert _snapshot(repo.folder) == before


def test_the_refusal_carries_the_warnings_accumulated_before_it(tmp_path):
    repo = make_repo(tmp_path, files=[D(1), *_DUPLICATE])
    orphan = repo.folder / "ADR009V01-x.md.0123456789abcdef0123456789abcdef.tmp"
    orphan.write_bytes(b"partial")
    old = time.time() - 3600
    os.utime(orphan, (old, old))

    with pytest.raises(CommandError) as caught:
        approve.run(["--file", str(repo.paths[0])])

    assert caught.value.code == FailureCodes.REPOSITORY_INCONSISTENT
    assert not orphan.exists()
    assert any("orphan" in warning.lower() or orphan.name in warning for warning in caught.value.warnings)


@pytest.mark.parametrize("command", [approve, reject, undo, version, revise, supersede])
def test_a_file_command_refuses_a_target_outside_the_decisions_folder(tmp_path, command):
    state = "proposed" if command in (approve, reject) else "accepted"
    repo = make_repo(tmp_path, config={"lenrevision": 2}, files=[D(2), D(1, state=state)])
    moved = repo.root / "elsewhere" / repo.paths[1].name
    moved.parent.mkdir()
    repo.paths[1].replace(moved)
    before = moved.read_bytes()

    with pytest.raises(CommandError) as caught:
        command.run(["--file", str(moved)])

    assert caught.value.code == FailureCodes.TARGET_OUTSIDE_FOLDERADR
    assert moved.read_bytes() == before
    assert sorted(path.name for path in repo.folder.iterdir()) == [repo.paths[0].name]
    assert sorted(path.name for path in moved.parent.iterdir()) == [moved.name]


def test_migrate_refuses_two_legacy_files_that_would_share_a_number(tmp_path):
    repo = make_repo(tmp_path, config={"migrationpattern": "N00:04T04"})
    first = repo.folder / "0001first.md"
    second = repo.folder / "0001second.md"
    first.write_text("# First\n", encoding="utf-8")
    second.write_text("# Second\n", encoding="utf-8")

    with pytest.raises(CommandError) as caught:
        migrate.run(["--path", str(repo.root)])

    assert caught.value.code == FailureCodes.MIGRATION_DUPLICATE_NUMBERS_EXIST
    assert caught.value.data["files"] == sorted([str(first), str(second)])
    assert first.read_text(encoding="utf-8") == "# First\n"
    assert second.read_text(encoding="utf-8") == "# Second\n"
