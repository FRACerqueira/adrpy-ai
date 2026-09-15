import json

import pytest

from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _valid_config_dict():
    return {
        "folderadr": "doc/adr",
        "migrationpattern": "",
        "template": "template content",
        "prefix": "ADR",
        "lenseq": 3,
        "lenversion": 2,
        "lenrevision": 0,
        "separator": "-",
        "casetransform": "KebabCase",
        "statusnew": "Proposed",
        "statusacc": "Accepted",
        "statusrej": "Rejected",
        "statussup": "Superseded",
        "headerdisclaimer": "Do not remove this comment, lines and table",
        "headertitlefile": "File title md",
        "headerversion": "Version",
        "headerrevision": "Revision",
        "headerscope": "Scope",
        "headerdomain": "Domain",
        "headertitlestatuscreated": "Created",
        "headertitlestatuschanged": "Changed",
        "headertitlestatussuperseded": "Superseded",
        "headertablefields": "Fields",
        "headertablevalues": "Values",
        "headermigrated": "Migrated",
        "activeplugins": [],
        "disableplugins": False,
    }


def test_loads_real_repo_config_fixture():
    config = load_repo_config(FIXTURE_PATH)

    assert config.folderadr == "doc/adr"
    assert config.prefix == "ADR"
    assert config.lenseq == 3
    assert config.activeplugins == ["AdrIndexer"]
    assert config.disableplugins is False


def test_malformed_json_is_rejected():
    with pytest.raises(CommandError) as excinfo:
        parse_repo_config("{not json")

    assert excinfo.value.code == "config-invalid-json"


def test_missing_required_field_is_rejected():
    data = _valid_config_dict()
    del data["lenseq"]

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-missing-field"


def test_unexpected_field_is_rejected():
    data = _valid_config_dict()
    data["somethingextra"] = "nope"

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-unexpected-field"


def test_wrong_type_is_rejected():
    data = _valid_config_dict()
    data["lenseq"] = "three"

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-wrong-type"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("lenseq", 2, "config-lenseq-too-small"),
        ("lenseq", 7, "config-lenseq-too-large"),
        ("lenversion", 1, "config-lenversion-too-small"),
        ("lenversion", 5, "config-lenversion-too-large"),
        ("lenrevision", -1, "config-lenrevision-negative"),
        ("lenrevision", 4, "config-lenrevision-too-large"),
    ],
)
def test_out_of_range_numeric_fields_are_rejected(field, value, code):
    data = _valid_config_dict()
    data[field] = value

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == code


def test_invalid_separator_is_rejected():
    data = _valid_config_dict()
    data["separator"] = "~"

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-separator-invalid"


def test_invalid_casetransform_is_rejected():
    data = _valid_config_dict()
    data["casetransform"] = "ShoutCase"

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-casetransform-invalid"


def test_empty_required_string_field_is_rejected():
    data = _valid_config_dict()
    data["statusnew"] = ""

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-field-empty"


def test_field_names_are_case_insensitive():
    data = _valid_config_dict()
    data["FolderAdr"] = data.pop("folderadr")

    config = parse_repo_config(json.dumps(data))

    assert config.folderadr == "doc/adr"
