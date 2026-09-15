import json

from adrpy.cli import init
from adrpy.core.errors import CommandError, UsageError

import pytest


def _default_config_text():
    from importlib import resources

    return resources.files("adrpy.resources").joinpath("default_repo_config.json").read_text(encoding="utf-8")


def test_init_fresh_repo_writes_default_config_and_creates_folder(tmp_path):
    result = init.run(["--path", str(tmp_path)])

    config_path = tmp_path / "adr-config.adrplus"
    assert config_path.read_text(encoding="utf-8") == _default_config_text()
    assert (tmp_path / "doc" / "adr").is_dir()
    assert result["created"] == [str(config_path), str(tmp_path / "doc" / "adr")]


def test_init_refuses_when_config_already_exists_without_file(tmp_path):
    init.run(["--path", str(tmp_path)])

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-already-exists"


def test_init_with_file_overwrites_using_custom_config(tmp_path):
    custom = json.loads(_default_config_text())
    custom["folderadr"] = "decisions"
    file_path = tmp_path / "custom-config.json"
    file_path.write_text(json.dumps(custom), encoding="utf-8")

    result = init.run(["--path", str(tmp_path), "--file", str(file_path)])

    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == json.dumps(custom)
    assert (tmp_path / "decisions").is_dir()
    assert str(tmp_path / "decisions") in result["created"]


def test_init_file_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--file", str(tmp_path / "missing.json")])

    assert excinfo.value.code == "config-file-not-found"


def test_init_invalid_config_schema_propagates(tmp_path):
    custom = json.loads(_default_config_text())
    del custom["lenseq"]
    file_path = tmp_path / "bad-config.json"
    file_path.write_text(json.dumps(custom), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--file", str(file_path)])

    assert excinfo.value.code == "config-missing-field"


def test_init_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path / "does-not-exist")])

    assert excinfo.value.code == "target-directory-not-found"


def test_init_missing_path_argument_is_usage_error():
    with pytest.raises(UsageError):
        init.run([])


def test_init_unknown_argument_is_usage_error(tmp_path):
    with pytest.raises(UsageError):
        init.run(["--path", str(tmp_path), "--bogus", "x"])


def test_init_rejects_digit_overflow_against_existing_decisions(tmp_path):
    existing_adr_dir = tmp_path / "doc" / "adr"
    existing_adr_dir.mkdir(parents=True)
    (existing_adr_dir / "ADR1234V01-preexisting.md").write_text("irrelevant", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "lenseq-too-small-for-existing-decisions"


def test_init_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    exit_code = main(["init", "--path", str(tmp_path)])

    assert exit_code == EXIT_SUCCESS
    assert (tmp_path / "adr-config.adrplus").exists()


def test_init_rejects_folderadr_traversal_outside_repository(tmp_path):
    """`folderadr: "../.."` passes config.py's schema check (it isn't
    absolute), but must still be caught at the point of use -- a hostile
    config (e.g. from a cloned repo) must never be able to make init create
    a directory outside the target repository."""
    custom = json.loads(_default_config_text())
    custom["folderadr"] = "../../escape"
    file_path = tmp_path / "custom-config.json"
    file_path.write_text(json.dumps(custom), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--file", str(file_path)])

    assert excinfo.value.code == "path-outside-repository"


def test_init_rejects_seed_file_with_invalid_utf8_bytes(tmp_path):
    """Resilience audit R3, second call site of the same class: init's own
    --file read used a bare read_text(encoding="utf-8") too."""
    file_path = tmp_path / "custom-config.json"
    file_path.write_bytes(b'{"folderadr": "doc\xffadr"}')

    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--file", str(file_path)])

    assert excinfo.value.code == "config-invalid-encoding"
