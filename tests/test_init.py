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


def test_init_with_language_seeds_localized_labels_and_template(tmp_path):
    """The real adrplus's `language` app setting (adrplus.json) doesn't
    just affect interactive UI text -- it also picks the DEFAULT header/
    status labels and template content baked into a newly init'd repo
    (AdrPlusRepoConfig.cs's own field initializers read from a per-
    culture .resx; the default template file is swapped for a per-
    culture variant). Extracted verbatim from AdrSource's own resources,
    never hand-translated."""
    result = init.run(["--path", str(tmp_path), "--language", "pt-br"])

    config = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert config["statusnew"] == "Proposto"
    assert config["statusacc"] == "Aceito"
    assert config["headerversion"] == "Versão"
    assert config["headerscope"] == "Escopo"
    assert "Contexto e Declaração do Problema" in config["template"]
    # Everything NOT covered by the language pack keeps the built-in default.
    assert config["folderadr"] == "doc/adr"
    assert config["separator"] == "-"
    assert result["created"][0] == str(tmp_path / "adr-config.adrplus")


def test_init_rejects_unsupported_language(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        init.run(["--path", str(tmp_path), "--language", "klingon"])

    assert excinfo.value.code == "init-language-not-supported"


@pytest.mark.parametrize("language", init.SUPPORTED_LANGUAGES)
def test_init_accepts_every_supported_language(tmp_path, language):
    """Every language pack must itself pass the real schema validation
    (label length limits, ASCII-only prefix, ...) -- not just pt-br."""
    result = init.run(["--path", str(tmp_path), "--language", language])

    assert result["created"][0] == str(tmp_path / "adr-config.adrplus")
    config = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    assert config["prefix"] == "ADR"  # every language pack's prefix is ASCII "ADR"


def test_init_rejects_language_combined_with_file(tmp_path):
    file_path = tmp_path / "custom-config.json"
    file_path.write_text(_default_config_text(), encoding="utf-8")

    with pytest.raises(UsageError):
        init.run(["--path", str(tmp_path), "--file", str(file_path), "--language", "pt-br"])
