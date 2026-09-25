"""`config` validates the repository (core/consistency) before it changes
a guarded field -- folderadr, folderlog, a status label, separator,
migrationpattern -- and not for a read or any other field."""

import json

import pytest

from adrpy.cli import config
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError

from conftest import D, make_repo


def _duplicate_repo(tmp_path):
    # Two files with the same number, version and revision: inconsistent.
    repo = make_repo(tmp_path, files=[D(1, title="First", state="accepted"), D(1, title="Second", state="accepted")])
    assert len({path.name for path in repo.paths}) == 2
    return repo


@pytest.mark.parametrize(
    "flag, value",
    [
        ("migrationpattern", "N00:04T04"),
        ("folderlog", "doc/other-log"),
    ],
)
def test_config_refuses_a_guarded_field_change_on_an_inconsistent_repository(tmp_path, flag, value):
    """Allowed on a consistent repository with only current-scheme
    decisions (migrationpattern) or no log entries (folderlog), so only
    the validation can refuse it."""
    repo = _duplicate_repo(tmp_path)
    before = (repo.root / "adr-config.adrplus").read_bytes()

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(repo.root), f"--{flag}", value])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["duplicate-number"]
    assert (repo.root / "adr-config.adrplus").read_bytes() == before


@pytest.mark.parametrize(
    "flag, value",
    [
        ("migrationpattern", "N00:04T04"),
        ("folderlog", "doc/other-log"),
    ],
)
def test_config_allows_the_same_guarded_field_change_on_a_consistent_repository(tmp_path, flag, value):
    repo = make_repo(tmp_path, files=[D(1, title="First")])

    result = config.run(["--path", str(repo.root), f"--{flag}", value])

    assert result["updated_fields"] == [flag]


def test_config_does_not_validate_for_a_field_that_is_not_guarded(tmp_path):
    repo = _duplicate_repo(tmp_path)

    result = config.run(["--path", str(repo.root), "--lenseq", "4"])

    assert result["updated_fields"] == ["lenseq"]
    assert load_repo_config(repo.root / "adr-config.adrplus").lenseq == 4


def test_config_read_does_not_validate(tmp_path):
    repo = _duplicate_repo(tmp_path)

    result = config.run(["--path", str(repo.root)])

    assert result["updated_fields"] == []
    assert json.dumps(result["config"])


def test_config_prepares_migrate_on_a_repository_not_yet_migrated(tmp_path):
    """Files with no header are what a repository looks like before its
    one migrate: config must not refuse over them, or migrate's own
    prerequisite (a migrationpattern) could never be set -- the no-header
    hint points at migrate. Any other inconsistency still blocks."""
    from adrpy.cli import migrate

    repo = make_repo(tmp_path)
    (repo.folder / "ADR001V01-first.md").write_bytes(b"# First\n\nLegacy content\n")
    (repo.folder / "ADR002V01-second.md").write_bytes(b"# Second\n\nLegacy content\n")

    config.run(["--path", str(repo.root), "--migrationpattern", "N00:04T04"])
    result = migrate.run(["--path", str(repo.root)])

    assert len(result["migrated"]) == 2


def test_config_changes_migrationpattern_over_a_legacy_file_not_yet_migrated(tmp_path):
    """no-header does not block config, and neither does the guard (owner
    decision): a legacy file with no header is not a decision yet, so a
    wrong migrationpattern can be fixed before migrate. A migrated one
    still blocks it (tests/test_config_command.py)."""
    repo = make_repo(tmp_path, config={"migrationpattern": "N00:04T04"})
    (repo.folder / "0001T01.md").write_bytes(b"Legacy content\n")

    result = config.run(["--path", str(repo.root), "--migrationpattern", "N00:05T05"])

    assert result["updated_fields"] == ["migrationpattern"]
