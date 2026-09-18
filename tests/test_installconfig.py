import json
from pathlib import Path

import pytest

from adrpy.cli import installconfig
from adrpy.core.config import parse_repo_config
from adrpy.core.errors import CommandError

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


@pytest.fixture(autouse=True)
def _isolated_install_config_path(monkeypatch, tmp_path):
    target = tmp_path / "install-config.json"
    monkeypatch.setattr(installconfig, "resolve_install_config_path", lambda: target)
    return target


def test_bare_read_reports_not_configured_when_file_missing(tmp_path):
    result = installconfig.run([])

    assert result["configured"] is False
    assert "config" not in result
    assert result["updated_fields"] == []  # present on every read, same shape as config.py's own
    assert result["warnings"] == []


def test_write_creates_the_file_from_the_bundled_default_and_merges_the_flag(tmp_path):
    result = installconfig.run(["--prefix", "XYZ"])

    assert result["updated_fields"] == ["prefix"]
    read_back = installconfig.run([])
    assert read_back["configured"] is True
    assert read_back["config"]["prefix"] == "XYZ"
    assert read_back["config"]["lenseq"] == 3  # bundled default, untouched
    assert "activeplugins" not in read_back["config"]  # never exposed, same as config
    assert read_back["updated_fields"] == []  # present on every read too


def test_second_write_merges_onto_the_existing_file_not_the_bundled_default(tmp_path):
    installconfig.run(["--prefix", "XYZ"])

    result = installconfig.run(["--lenseq", "4"])

    assert result["updated_fields"] == ["lenseq"]
    read_back = installconfig.run([])
    assert read_back["config"]["prefix"] == "XYZ"  # from the first write, preserved
    assert read_back["config"]["lenseq"] == 4


def test_activeplugins_is_preserved_across_writes_even_though_never_exposed(tmp_path):
    installconfig.run(["--seed", FIXTURE_PATH])  # fixture's activeplugins == ["AdrIndexer"]

    installconfig.run(["--prefix", "XYZ"])

    target_path = installconfig.resolve_install_config_path()
    written = parse_repo_config(target_path.read_text(encoding="utf-8"))
    assert written.activeplugins == ["AdrIndexer"]
    assert written.prefix == "XYZ"


def test_seed_replaces_the_file_wholesale(tmp_path):
    result = installconfig.run(["--seed", FIXTURE_PATH])

    assert set(result["updated_fields"]) == set(installconfig._EDITABLE_FIELDS)
    target_path = installconfig.resolve_install_config_path()
    assert target_path.read_text(encoding="utf-8") == Path(FIXTURE_PATH).read_text(encoding="utf-8")


def test_seed_rejects_content_that_fails_schema_validation(tmp_path):
    """Round 11 test-adequacy pass: zero coverage existed for a --seed
    file that exists and is readable but fails schema validation --
    mutation-confirmed that removing installconfig.py's own
    `parse_repo_config(seed_text)` validate-before-write call left every
    existing test green."""
    data = json.loads(Path(FIXTURE_PATH).read_text(encoding="utf-8"))
    del data["lenseq"]
    bad_seed = tmp_path / "bad-seed.json"
    bad_seed.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        installconfig.run(["--seed", str(bad_seed)])

    assert excinfo.value.code == "config-missing-field"
    assert not installconfig.resolve_install_config_path().exists()


def test_seed_rejects_a_missing_file(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        installconfig.run(["--seed", str(tmp_path / "missing.json")])

    assert excinfo.value.code == "config-file-not-found"


def test_seed_does_not_merge_with_field_flags(tmp_path):
    """--seed replaces wholesale -- confirms a field flag passed alongside
    --seed is simply ignored (parse_flags accepts it since it's a
    declared optional flag), not silently applied on top, matching
    init --seed's own precedent of ignoring co-passed field content."""
    installconfig.run(["--seed", FIXTURE_PATH, "--prefix", "ZZZ"])

    read_back = installconfig.run([])
    assert read_back["config"]["prefix"] == "ADR"  # the fixture's own value, not "ZZZ"


def test_invalid_field_value_is_rejected(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        installconfig.run(["--lenseq", "2"])

    assert excinfo.value.code == "config-lenseq-too-small"


def test_disableplugins_accepts_true_and_false(tmp_path):
    result = installconfig.run(["--disableplugins", "true"])

    assert result["updated_fields"] == ["disableplugins"]
    assert installconfig.run([])["config"]["disableplugins"] is True


def test_disableplugins_rejects_a_non_boolean_value(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        installconfig.run(["--disableplugins", "maybe"])

    assert excinfo.value.code == "field-not-a-boolean"


def test_describe_has_no_path_argument_and_no_activeplugins_flag():
    info = installconfig.describe()

    names = [arg["name"] for arg in info["arguments"]]
    assert "path" not in names
    assert "activeplugins" not in names
    assert "seed" in names


def test_write_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    real_atomic_write_text = installconfig.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(installconfig, "atomic_write_text", flaky_atomic_write_text)

    result = installconfig.run(["--prefix", "XYZ"])

    assert result["warnings"] == ["Write succeeded only after 3 attempts due to transient contention."]
