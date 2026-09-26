"""A migrationpattern whose T (title start) lies inside one of its N/V/R/P
ranges, or two of whose ranges overlap, reads the same characters twice
(e.g. 'N00:04T02' on 0001-use-x.md records the title '01-use-x'). It is
refused where it is SET (config, installconfig, init, explore's preview)
and by migrate, never when a config is merely loaded: a repository that
already holds one keeps working and can still change it."""

import json

import pytest

from adrpy.cli import config, explore, init, installconfig, migrate
from adrpy.core.config import parse_repo_config
from adrpy.core.consistency import check_repository
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.naming import migration_pattern_overlap

from conftest import FIXTURE_CONFIG, D, make_repo

_BAD = "N00:04T02"


def _tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def _legacy(repo, name="0001-use-x.md"):
    (repo.folder / name).write_text("# Use x\n", encoding="utf-8")


def _refused(call):
    with pytest.raises(CommandError) as excinfo:
        call()
    assert excinfo.value.code == FailureCodes.CONFIG_MIGRATIONPATTERN_INVALID
    return excinfo.value


# ------------------------------------------------------------- predicate --


@pytest.mark.parametrize(
    "pattern, detail",
    [
        ("N00:04T02", "T02 starts inside N00:04: the title would begin with the number's last digits"),
        ("N00:04T00", "T00 starts inside N00:04: the title would begin with the number's digits"),
        ("N00:04T06V05:02", "T06 starts inside V05:02: the title would begin with the version's last digits"),
        ("N03:04T01P00:03", "T01 starts inside P00:03: the title would begin with the prefix's last characters"),
        ("N00:04T06V03:02", "N00:04 and V03:02 overlap: the same characters would be read as both the number and the version"),
        ("N02:04T07R00:03", "N02:04 and R00:03 overlap: the same characters would be read as both the number and the revision"),
    ],
)
def test_an_overlapping_pattern_is_named_with_the_overlap(pattern, detail):
    assert migration_pattern_overlap(pattern) == detail


@pytest.mark.parametrize("pattern", ["N00:04T04", "N00:04T05", "N00:04T08V05:02", "N03:04T08P00:03", "", "bogus"])
def test_a_pattern_without_overlap_is_not_flagged(pattern):
    # An empty or unparseable pattern is not this predicate's concern
    # (parse_repo_config's own shape check refuses the unparseable one).
    assert migration_pattern_overlap(pattern) is None


# -------------------------------------------------------- setting points --


def test_config_refuses_an_overlapping_migrationpattern_and_leaves_the_config_untouched(tmp_path):
    repo = make_repo(tmp_path)
    _legacy(repo)
    before = _tree(repo.root)

    error = _refused(lambda: config.run(["--path", str(repo.root), "--migrationpattern", _BAD]))

    assert "T02 starts inside N00:04" in error.detail
    assert _tree(repo.root) == before


def test_config_still_sets_a_correct_pattern(tmp_path):
    repo = make_repo(tmp_path)
    _legacy(repo)

    result = config.run(["--path", str(repo.root), "--migrationpattern", "N00:04T05"])

    assert [entry["title"] for entry in result["migrationpattern_preview"]] == ["use-x"]


def test_explore_refuses_to_preview_an_overlapping_migrationpattern(tmp_path):
    repo = make_repo(tmp_path)
    _legacy(repo)

    error = _refused(lambda: explore.run(["--path", str(repo.root), "--migrationpattern", _BAD]))

    assert "T02 starts inside N00:04" in error.detail


@pytest.fixture
def install_target(monkeypatch, tmp_path):
    target = tmp_path / "install" / "install-config.json"
    monkeypatch.setattr(installconfig, "resolve_install_config_path", lambda: target)
    return target


def _seed(tmp_path, pattern, name="seed.json"):
    data = json.loads(FIXTURE_CONFIG.read_text(encoding="utf-8"))
    data["migrationpattern"] = pattern
    path = tmp_path / name
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def test_installconfig_refuses_an_overlapping_migrationpattern_flag(install_target):
    installconfig.run(["--prefix", "XYZ"])
    before = install_target.read_bytes()

    error = _refused(lambda: installconfig.run(["--migrationpattern", _BAD]))

    assert "T02 starts inside N00:04" in error.detail
    assert install_target.read_bytes() == before


def test_installconfig_refuses_a_seed_carrying_an_overlapping_migrationpattern(install_target, tmp_path):
    seed = _seed(tmp_path, _BAD)

    _refused(lambda: installconfig.run(["--seed", str(seed)]))

    assert not install_target.exists()


def test_init_refuses_a_seed_carrying_an_overlapping_migrationpattern(tmp_path):
    seed = _seed(tmp_path, _BAD)
    repo = tmp_path / "repo"
    repo.mkdir()

    _refused(lambda: init.run(["--path", str(repo), "--seed", str(seed)]))

    assert list(repo.iterdir()) == []


def test_init_refuses_an_install_level_config_carrying_an_overlapping_migrationpattern(tmp_path, monkeypatch):
    text = _seed(tmp_path, _BAD).read_text(encoding="utf-8")
    monkeypatch.setattr(init, "read_install_config_text", lambda *args, **kwargs: text)
    repo = tmp_path / "repo"
    repo.mkdir()

    _refused(lambda: init.run(["--path", str(repo)]))

    assert list(repo.iterdir()) == []


def test_init_seed_over_a_repository_that_already_has_that_pattern_is_not_refused_for_it(tmp_path):
    # Not a setting of the pattern: the one already in place stays, and
    # the other fields of the seed still apply.
    repo = make_repo(tmp_path / "repo", config={"migrationpattern": _BAD})
    seed = _seed(tmp_path, _BAD)

    init.run(["--path", str(repo.root), "--seed", str(seed)])

    assert parse_repo_config((repo.root / "adr-config.adrplus").read_text(encoding="utf-8")).migrationpattern == _BAD


# ------------------------------------------------------- already in place --


def test_a_config_already_holding_an_overlapping_pattern_still_loads_and_can_change(tmp_path, capsys):
    from adrpy.__main__ import main

    repo = make_repo(
        tmp_path,
        config={"migrationpattern": _BAD},
        files=[D(1, version=0, migrated=True, state="placeholder", filename="0001-use-x.md")],
    )

    assert main(["check", "--path", str(repo.root)]) == 0
    capsys.readouterr()
    config.run(["--path", str(repo.root), "--lenseq", "4"])
    assert parse_repo_config((repo.root / "adr-config.adrplus").read_text(encoding="utf-8")).lenseq == 4


def test_a_repository_holding_an_overlapping_pattern_can_clear_or_correct_it(tmp_path):
    repo = make_repo(tmp_path, config={"migrationpattern": _BAD})
    _legacy(repo)

    config.run(["--path", str(repo.root), "--migrationpattern", ""])
    config.run(["--path", str(repo.root), "--migrationpattern", "N00:04T05"])

    assert parse_repo_config((repo.root / "adr-config.adrplus").read_text(encoding="utf-8")).migrationpattern == "N00:04T05"


# ---------------------------------------------------------------- migrate --


def test_migrate_refuses_the_repositorys_own_overlapping_pattern_without_writing(tmp_path):
    repo = make_repo(tmp_path, config={"migrationpattern": _BAD})
    _legacy(repo)
    before = _tree(repo.root)

    error = _refused(lambda: migrate.run(["--path", str(repo.root)]))

    assert "T02 starts inside N00:04" in error.detail
    assert _tree(repo.root) == before


def test_migrate_finishes_a_partial_adoption_under_an_overlapping_pattern_with_a_warning(tmp_path):
    # Once a decision was migrated with the pattern, the guard keeps it
    # from changing: refusing here would leave the rest unmigratable.
    repo = make_repo(
        tmp_path,
        config={"migrationpattern": _BAD},
        files=[D(1, version=0, migrated=True, state="placeholder", filename="0001-use-x.md")],
    )
    _legacy(repo, "0002-use-y.md")

    result = migrate.run(["--path", str(repo.root)])

    assert result["migrated"] == [str(repo.folder / "0002-use-y.md")]
    [warning] = [w for w in result["warnings"] if "reads part of a name twice" in w]
    assert "T02 starts inside N00:04" in warning and "by hand" in warning
    assert check_repository(repo.folder, parse_repo_config((repo.root / "adr-config.adrplus").read_text(encoding="utf-8")))[1] == []


def test_migrate_refuses_an_overlapping_fallback_before_persisting_it(tmp_path, monkeypatch):
    text = _seed(tmp_path, _BAD).read_text(encoding="utf-8")
    monkeypatch.setattr(migrate, "read_install_config_text", lambda *args, **kwargs: text)
    repo = make_repo(tmp_path / "repo")
    _legacy(repo)
    before = _tree(repo.root)

    error = _refused(lambda: migrate.run(["--path", str(repo.root)]))

    assert "migrationpattern_persisted" not in (error.data or {})
    assert _tree(repo.root) == before


def test_migrate_with_a_correct_pattern_still_migrates(tmp_path):
    repo = make_repo(tmp_path, config={"migrationpattern": "N00:04T05"})
    _legacy(repo)

    result = migrate.run(["--path", str(repo.root)])

    assert result["migrated"] == [str(repo.folder / "0001-use-x.md")]
