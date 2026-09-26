"""Every command that creates a file creates it exclusively: a name that
appears between the command's own checks and its commit is refused with
that command's own code, and the file already there is left byte-for-byte
as it was. Each test plants the file from a hook that runs after every
check the command makes and before its write, so only the commit itself
can notice it."""

import json

import pytest

from adrpy.cli import approve, init, log, new, revise, supersede, version
from adrpy.core.errors import CommandError

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"
PLANTED = b"planted by someone else\n"


def _plant_then_call(monkeypatch, module, name, target):
    real = getattr(module, name)

    def planting(*args, **kwargs):
        target.write_bytes(PLANTED)
        return real(*args, **kwargs)

    monkeypatch.setattr(module, name, planting)


def _new_decision(tmp_path):
    new.run(
        [
            "--path", str(tmp_path), "--title", "Use PostgreSQL", "--domain", "Backend",
            "--scope", "Data", "--refdate", "2026-01-01",
        ]
    )
    return tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"


def _accepted(tmp_path):
    init.run(["--path", str(tmp_path)])
    path = _new_decision(tmp_path)
    approve.run(["--file", str(path), "--refdate", "2026-01-02"])
    return path


def _accepted_with_revisions(tmp_path):
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["lenrevision"] = 2
    seed = tmp_path / "seed-config.json"
    seed.write_text(json.dumps(data), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(seed)])
    new.run(
        [
            "--path", str(tmp_path), "--title", "Use PostgreSQL", "--domain", "Backend",
            "--scope", "Data", "--refdate", "2026-01-01",
        ]
    )
    path = tmp_path / "doc" / "adr" / "ADR001V01R01-use-postgre-sql.md"
    approve.run(["--file", str(path), "--refdate", "2026-01-02"])
    return path


def _no_temp_left(folder):
    return [p.name for p in folder.rglob("*.tmp")] == []


@pytest.fixture(params=["current", "other"])
def platform_branch(request, monkeypatch):
    """Runs each test on this OS's exclusive-create branch and on the
    other OS's. The Windows branch (os.rename) only refuses an existing
    target on Windows -- POSIX rename replaces it, which is why POSIX
    uses os.link -- so it can't be exercised from a POSIX host."""
    if request.param == "other":
        from adrpy.core import fs

        if not fs._IS_WINDOWS:
            pytest.skip("POSIX os.rename replaces an existing target; the Windows branch needs Windows")
        monkeypatch.setattr(fs, "_IS_WINDOWS", False)
    return request.param


def test_new_refuses_a_name_that_appears_before_its_commit(tmp_path, monkeypatch, platform_branch):
    init.run(["--path", str(tmp_path)])
    target = tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"
    _plant_then_call(monkeypatch, new, "build_header", target)

    with pytest.raises(CommandError) as excinfo:
        _new_decision(tmp_path)

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": target.name}
    assert target.read_bytes() == PLANTED
    assert _no_temp_left(tmp_path)


def test_version_refuses_a_name_that_appears_before_its_commit(tmp_path, monkeypatch, platform_branch):
    path = _accepted(tmp_path)
    target = path.with_name("ADR001V02-use-postgre-sql.md")
    _plant_then_call(monkeypatch, version, "build_header", target)

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(path), "--refdate", "2026-01-03"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": target.name}
    assert target.read_bytes() == PLANTED
    assert _no_temp_left(tmp_path)


def test_version_empty_refuses_a_name_that_appears_before_its_commit(tmp_path, monkeypatch, platform_branch):
    path = _accepted(tmp_path)
    target = path.with_name("ADR001V02-use-postgre-sql.md")
    _plant_then_call(monkeypatch, version, "build_header", target)

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(path), "--refdate", "2026-01-03", "--empty"])

    assert excinfo.value.code == "file-already-exists"
    assert target.read_bytes() == PLANTED
    assert _no_temp_left(tmp_path)


def test_revise_refuses_a_name_that_appears_before_its_commit(tmp_path, monkeypatch, platform_branch):
    path = _accepted_with_revisions(tmp_path)
    target = path.with_name("ADR001V01R02-use-postgre-sql.md")
    _plant_then_call(monkeypatch, revise, "build_header", target)

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(path), "--refdate", "2026-01-03"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": target.name}
    assert target.read_bytes() == PLANTED
    assert _no_temp_left(tmp_path)


def test_supersede_refuses_a_successor_name_that_appears_before_its_commit(tmp_path, monkeypatch, platform_branch):
    path = _accepted(tmp_path)
    before = path.read_bytes()
    target = path.with_name("ADR002V01-use-postgre-sql--001.md")
    _plant_then_call(monkeypatch, supersede, "build_header", target)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(path), "--refdate", "2026-01-03"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": target.name}
    assert target.read_bytes() == PLANTED
    # Nothing applied: the predecessor is not marked either.
    assert path.read_bytes() == before
    assert _no_temp_left(tmp_path)


LOG_ARGS = [
    "--classification", "scope-note", "--scope", "core", "--slug", "dup",
    "--summary", "First", "--body", "x", "--refdate", "2026-09-18",
]


def test_log_refuses_an_entry_name_that_appears_before_its_commit(tmp_path, monkeypatch, platform_branch):
    init.run(["--path", str(tmp_path)])
    log_dir = tmp_path / "doc" / "decision-log"
    log_dir.mkdir(parents=True)
    target = log_dir / "2026-09-18--scope-note--core--dup.md"
    _plant_then_call(monkeypatch, log, "build_entry_content", target)

    with pytest.raises(CommandError) as excinfo:
        log.run(["--path", str(tmp_path), *LOG_ARGS])

    assert excinfo.value.code == "log-entry-already-exists"
    assert excinfo.value.data == {"file": target.name}
    assert target.read_bytes() == PLANTED
    assert _no_temp_left(tmp_path)


def test_init_refuses_a_config_that_appears_before_its_commit(tmp_path, monkeypatch, platform_branch):
    target = tmp_path / "adr-config.adrplus"
    _plant_then_call(monkeypatch, init, "reject_aliased_repo_folders", target)

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-already-exists"
    assert target.read_bytes() == PLANTED
    assert _no_temp_left(tmp_path)


def test_log_refuses_an_entry_name_too_long_for_the_filesystem(tmp_path):
    init.run(["--path", str(tmp_path)])

    with pytest.raises(CommandError) as excinfo:
        log.run([
            "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock",
            "--slug", "a" * 202, "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
        ])

    assert excinfo.value.code == "filename-too-long"
    assert "--slug" in excinfo.value.detail


@pytest.mark.parametrize("command", [revise, version])
def test_a_revision_or_version_too_long_for_the_filesystem_says_to_supersede(tmp_path, command):
    # Neither command takes --title: the way out is a supersede with a
    # shorter one.
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "a" * 221, "--refdate", "2026-01-01"])
    path = tmp_path / "doc" / "adr" / f"ADR001V01-{'a' * 221}.md"
    approve.run(["--file", str(path), "--refdate", "2026-01-02"])
    from adrpy.cli import config
    config.run(["--path", str(tmp_path), "--lenrevision", "2"])

    with pytest.raises(CommandError) as excinfo:
        command.run(["--file", str(path), "--refdate", "2026-01-03"])

    assert excinfo.value.code == "filename-too-long"
    assert "adrpy supersede" in excinfo.value.detail and "--title" in excinfo.value.detail


def test_log_too_long_names_both_flags_that_make_up_the_name(tmp_path):
    init.run(["--path", str(tmp_path)])

    with pytest.raises(CommandError) as excinfo:
        log.run([
            "--path", str(tmp_path), "--classification", "scope-note", "--scope", "a" * 210,
            "--slug", "x", "--summary", "x", "--body", "x", "--refdate", "2026-09-18",
        ])

    assert excinfo.value.code == "filename-too-long"
    assert "--scope" in excinfo.value.detail and "--slug" in excinfo.value.detail
