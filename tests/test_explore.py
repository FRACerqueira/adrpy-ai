import json
from datetime import date

from adrpy.cli import explore
from adrpy.core.config import parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header

import pytest

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _default_config_dict():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write_repo(tmp_path, config_dict, decisions):
    config_text = json.dumps(config_dict)
    (tmp_path / "adr-config.adrplus").write_text(config_text, encoding="utf-8")
    config = parse_repo_config(config_text)

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in decisions.items():
        # newline="": content already carries build_header's real line
        # endings (os.linesep) -- the default write-mode translation would
        # double every "\r" into "\r\r\n", corrupting the fixed 12-line
        # header that parse_header expects.
        with open(adr_dir / filename, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    return config


def _decision_text(config, **record_kwargs):
    record = DecisionRecord(**record_kwargs)
    return build_header(config, record) + "# body"


def test_explore_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        explore.run(["--path", str(tmp_path / "missing")])

    assert excinfo.value.code == "target-directory-not-found"


def test_explore_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        explore.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-not-found"


def test_explore_returns_empty_when_adr_folder_missing(tmp_path):
    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    result = explore.run(["--path", str(tmp_path)])

    assert result["decisions"] == []


def test_explore_lists_recognized_and_unrecognized_files(tmp_path):
    config_dict = _default_config_dict()
    config = _write_repo(
        tmp_path,
        config_dict,
        {
            "ADR001V01-first-decision.md": _decision_text(
                parse_repo_config(json.dumps(config_dict)),
                number=1,
                title="First decision",
                version=1,
                status_create="Proposed",
                date_create=date(2026, 1, 1),
            ),
            "not-an-adr.md": "# just some markdown",
        },
    )

    result = explore.run(["--path", str(tmp_path)])
    by_name = {entry["filename"]: entry for entry in result["decisions"]}

    assert by_name["ADR001V01-first-decision.md"]["scheme"] == "current"
    assert by_name["ADR001V01-first-decision.md"]["number"] == 1
    assert by_name["ADR001V01-first-decision.md"]["title"] == "first-decision"
    assert by_name["ADR001V01-first-decision.md"]["header"]["is_valid"] is True
    assert by_name["ADR001V01-first-decision.md"]["header"]["status_create"] == "Proposed"
    assert by_name["ADR001V01-first-decision.md"]["header"]["date_create"] == "2026-01-01"
    # Usability audit A1: the full path, not just the bare filename -- an
    # agent needs this to act on the entry (--file on approve/reject/...)
    # without re-deriving folder/filename itself, which isn't safe under a
    # recursive scan that could have subfolders.
    assert by_name["ADR001V01-first-decision.md"]["path"] == str(
        tmp_path / config_dict["folderadr"] / "ADR001V01-first-decision.md"
    )

    assert by_name["not-an-adr.md"]["scheme"] is None
    assert by_name["not-an-adr.md"]["number"] == 0
    assert by_name["not-an-adr.md"]["header"]["is_valid"] is False


def test_explore_exposes_scope_and_domain(tmp_path):
    """Fidelity audit F14: the real tool's own report has Scope/Domain
    columns; adrpy's JSON dropped both entirely."""
    config_dict = _default_config_dict()
    _write_repo(
        tmp_path,
        config_dict,
        {
            "ADR001V01-first-decision.md": _decision_text(
                parse_repo_config(json.dumps(config_dict)),
                number=1,
                title="First decision",
                version=1,
                scope="Data",
                domain="Backend",
            ),
        },
    )

    result = explore.run(["--path", str(tmp_path)])

    entry = result["decisions"][0]
    assert entry["header"]["scope"] == "Data"
    assert entry["header"]["domain"] == "Backend"


def test_explore_sorts_by_validity_then_migrated_then_descending_numbers(tmp_path):
    config_dict = _default_config_dict()
    config = parse_repo_config(json.dumps(config_dict))
    decisions = {
        "ADR001V01-old-version.md": _decision_text(config, number=1, title="Old", version=1),
        "ADR001V02-new-version.md": _decision_text(config, number=1, title="New", version=2),
        "unrecognized.md": "not a header at all",
    }
    _write_repo(tmp_path, config_dict, decisions)

    result = explore.run(["--path", str(tmp_path)])
    order = [entry["filename"] for entry in result["decisions"]]

    assert order == [
        "ADR001V02-new-version.md",
        "ADR001V01-old-version.md",
        "unrecognized.md",
    ]


def test_explore_recognizes_legacy_scheme_too(tmp_path):
    config_dict = _default_config_dict()
    config_dict["migrationpattern"] = "N00:04T04"
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")
    (adr_dir / "0001UsePostgreSQL.md").write_text("# legacy content, no header yet", encoding="utf-8")
    with open(adr_dir / "ADR002V01-current-scheme.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(_decision_text(config, number=2, title="Current scheme", version=1))

    result = explore.run(["--path", str(tmp_path)])
    by_name = {entry["filename"]: entry for entry in result["decisions"]}

    assert by_name["0001UsePostgreSQL.md"]["scheme"] == "legacy"
    assert by_name["0001UsePostgreSQL.md"]["number"] == 1
    assert by_name["0001UsePostgreSQL.md"]["title"] == "UsePostgreSQL"
    assert by_name["ADR002V01-current-scheme.md"]["scheme"] == "current"


def test_explore_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    exit_code = main(["explore", "--path", str(tmp_path)])

    assert exit_code == EXIT_SUCCESS


def test_explore_accepts_short_flag_end_to_end_through_main(tmp_path):
    """Fidelity audit F10: real adrplus's -p; end-to-end through main(),
    not just parse_flags in isolation."""
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    assert main(["explore", "-p", str(tmp_path)]) == EXIT_SUCCESS
