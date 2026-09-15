import json

from adrpy.cli import config, init
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError, UsageError

import pytest


def _init_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    return tmp_path


def test_config_updates_a_single_field_and_preserves_the_rest(tmp_path):
    tmp_path = _init_repo(tmp_path)
    before = load_repo_config(tmp_path / "adr-config.adrplus")

    result = config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    assert result["updated_fields"] == ["prefix"]
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.prefix == "DOC"
    assert after.folderadr == before.folderadr
    assert after.lenseq == before.lenseq
    assert after.activeplugins == before.activeplugins  # untouched, not exposed


def test_config_updates_multiple_fields_at_once(tmp_path):
    tmp_path = _init_repo(tmp_path)

    result = config.run(
        ["--path", str(tmp_path), "--folderadr", "decisions", "--separator", "_", "--lenseq", "4"]
    )

    assert set(result["updated_fields"]) == {"folderadr", "separator", "lenseq"}
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.folderadr == "decisions"
    assert after.separator == "_"
    assert after.lenseq == 4


def test_config_omitted_fields_keep_current_value(tmp_path):
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    config.run(["--path", str(tmp_path), "--headertitlefile", "Title"])

    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.prefix == "DOC"  # set earlier, preserved by the second call
    assert after.headertitlefile == "Title"


def test_config_toggles_disableplugins(tmp_path):
    tmp_path = _init_repo(tmp_path)

    config.run(["--path", str(tmp_path), "--disableplugins", "true"])
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is True

    config.run(["--path", str(tmp_path), "--disableplugins", "false"])
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is False


def test_config_rejects_invalid_disableplugins_value(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--disableplugins", "maybe"])

    assert excinfo.value.code == "field-not-a-boolean"


def test_config_rejects_non_integer_lenseq(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "three"])

    assert excinfo.value.code == "field-not-an-integer"


def test_config_still_enforces_schema_bounds(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "99"])

    assert excinfo.value.code == "config-lenseq-too-large"


def test_config_rejects_invalid_merged_value_leaves_file_untouched(tmp_path):
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8")

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--separator", "~"])

    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == before


def test_config_does_not_expose_activeplugins(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(UsageError):
        config.run(["--path", str(tmp_path), "--activeplugins", "Foo"])


def test_config_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path / "missing"), "--prefix", "X"])

    assert excinfo.value.code == "target-directory-not-found"


def test_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "X"])

    assert excinfo.value.code == "config-not-found"


def test_config_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path = _init_repo(tmp_path)

    assert main(["config", "--path", str(tmp_path), "--prefix", "DOC"]) == EXIT_SUCCESS
