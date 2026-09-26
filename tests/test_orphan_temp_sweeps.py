"""The temp files a write outside folderadr can leave behind (the repo's
adr-config.adrplus, the decision log's INDEX.md and entries, the
install-level config) are swept at the start of the command that writes
there, with the same 30 s age rule as the folderadr sweep: an old one is
removed and reported, a young one (maybe another call's, in flight) kept."""

import json
import os
import time
import uuid

import pytest

from adrpy.cli import config, init, installconfig, log, migrate


def _orphan(path, age):
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:16]}.tmp")
    temp.write_bytes(b"partial")
    stamp = time.time() - age
    os.utime(temp, (stamp, stamp))
    return temp


def _old_and_young(path):
    return _orphan(path, 120), _orphan(path, 0)


def _assert_swept(old, young, warnings):
    assert not old.exists()
    assert young.exists()
    assert any(old.name in warning for warning in warnings)


def test_config_sweeps_its_own_orphaned_temps(tmp_path):
    init.run(["--path", str(tmp_path)])
    old, young = _old_and_young(tmp_path / "adr-config.adrplus")

    result = config.run(["--path", str(tmp_path), "--lenseq", "4"])

    _assert_swept(old, young, result["warnings"])


def test_init_sweeps_the_orphaned_temps_of_the_config_it_writes(tmp_path):
    old, young = _old_and_young(tmp_path / "adr-config.adrplus")

    result = init.run(["--path", str(tmp_path)])

    _assert_swept(old, young, result["warnings"])


def test_init_seed_sweeps_the_orphaned_temps_of_the_config_it_replaces(tmp_path):
    init.run(["--path", str(tmp_path)])
    seed = tmp_path / "seed.json"
    seed.write_text(init.default_repo_config_text(), encoding="utf-8")
    old, young = _old_and_young(tmp_path / "adr-config.adrplus")

    result = init.run(["--path", str(tmp_path), "--seed", str(seed)])

    _assert_swept(old, young, result["warnings"])


def test_migrate_sweeps_the_orphaned_temps_of_the_config_it_may_write(tmp_path):
    init.run(["--path", str(tmp_path)])
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    (tmp_path / "doc" / "adr" / "0001UsePostgres.md").write_bytes(b"# Use Postgres\n")
    old, young = _old_and_young(tmp_path / "adr-config.adrplus")

    result = migrate.run(["--path", str(tmp_path)])

    _assert_swept(old, young, result["warnings"])


def test_log_sweeps_the_orphaned_temps_in_its_folder(tmp_path):
    init.run(["--path", str(tmp_path)])
    folder = tmp_path / "doc" / "decision-log"
    folder.mkdir(parents=True)
    old, young = _old_and_young(folder / "INDEX.md")
    old_entry = _orphan(folder / "2026-01-01--scope-note--lock--earlier.md", 120)

    result = log.run(
        [
            "--path", str(tmp_path),
            "--classification", "scope-note",
            "--scope", "lock",
            "--slug", "a-note",
            "--summary", "A clarifying note",
            "--body", "The body text.",
        ]
    )

    _assert_swept(old, young, result["warnings"])
    assert not old_entry.exists()


@pytest.fixture
def install_config_path(monkeypatch, tmp_path):
    target = tmp_path / "install" / "install-config.json"
    target.parent.mkdir()
    monkeypatch.setattr(installconfig, "resolve_install_config_path", lambda: target)
    return target


def test_installconfig_sweeps_the_orphaned_temps_of_its_file(install_config_path):
    old, young = _old_and_young(install_config_path)

    result = installconfig.run(["--prefix", "XYZ"])

    _assert_swept(old, young, result["warnings"])
    assert json.loads(install_config_path.read_text(encoding="utf-8"))["prefix"] == "XYZ"


def test_the_known_files_sweep_never_removes_a_link_named_like_its_own_temp(tmp_path):
    # A junction (or symlink) at the repository root that happens to carry
    # the config's own temp-file name is not a temp file this tool wrote:
    # only a regular file is swept, as in the folder sweeps (scan_tree).
    import subprocess
    import sys

    from adrpy.core.fs import cleanup_orphaned_temp_files_for

    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("user data", encoding="utf-8")
    stamp = time.time() - 120
    os.utime(outside, (stamp, stamp))
    config_path = tmp_path / "repo" / "adr-config.adrplus"
    config_path.parent.mkdir()
    link = config_path.with_name(f"{config_path.name}.{uuid.uuid4().hex[:16]}.tmp")
    if sys.platform == "win32":
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(outside)], check=True, capture_output=True)
    else:
        os.symlink(outside, link, target_is_directory=True)

    removed = cleanup_orphaned_temp_files_for([config_path])

    assert removed == []
    assert os.path.lexists(link)
    assert (outside / "keep.txt").exists()
