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


@pytest.mark.parametrize("prefix", ["", "A", "ADR", "ABCDE"])
def test_valid_prefixes_are_accepted(prefix):
    data = _valid_config_dict()
    data["prefix"] = prefix

    config = parse_repo_config(json.dumps(data))

    assert config.prefix == prefix


@pytest.mark.parametrize("prefix", ["ABCDEF", "AD1", "AD-R", "adr "])
def test_invalid_prefixes_are_rejected(prefix):
    data = _valid_config_dict()
    data["prefix"] = prefix

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-prefix-invalid"


def test_folderadr_too_long_is_rejected():
    data = _valid_config_dict()
    data["folderadr"] = "d" * 51

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-folderadr-too-long"


@pytest.mark.parametrize(
    "folderadr",
    [
        r"C:\Windows\System32",
        "/etc/passwd",
        r"C:foo",
        r"\\server\share",
        "//server/share",
    ],
)
def test_absolute_folderadr_is_rejected(folderadr):
    data = _valid_config_dict()
    data["folderadr"] = folderadr

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-folderadr-not-relative"


@pytest.mark.parametrize("folderadr", ["doc/adr", "decisions", "../still-relative"])
def test_relative_folderadr_is_accepted(folderadr):
    data = _valid_config_dict()
    data["folderadr"] = folderadr

    config = parse_repo_config(json.dumps(data))

    assert config.folderadr == folderadr


def test_headerdisclaimer_too_long_is_rejected():
    data = _valid_config_dict()
    data["headerdisclaimer"] = "d" * 101

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-headerdisclaimer-too-long"


def test_header_label_too_long_is_rejected():
    data = _valid_config_dict()
    data["headertitlefile"] = "d" * 41

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-headertitlefile-too-long"


def test_status_label_too_long_is_rejected():
    data = _valid_config_dict()
    data["statusnew"] = "d" * 26

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-statusnew-too-long"


@pytest.mark.parametrize(
    "field",
    [
        "headertitlefile",
        "headerversion",
        "headerrevision",
        "headerscope",
        "headerdomain",
        "headertitlestatuscreated",
        "headertitlestatuschanged",
        "headertitlestatussuperseded",
        "headertablefields",
        "headertablevalues",
        "headermigrated",
        "headerdisclaimer",
        "statusnew",
        "statusacc",
        "statusrej",
        "statussup",
    ],
)
def test_header_cell_field_with_embedded_pipe_is_rejected(field):
    """Security audit F3: a header/status label reaching a header table
    cell verbatim, with no delimiter check, let a hostile config forge an
    extra header row -- e.g. `headertitlestatuschanged` containing its own
    '|Changed|Accepted (...)|' fabricates an approval no one ever granted.
    Confirmed live end-to-end (config -> new -> explore/supersede saw the
    forged Accepted status; approve then refused it as already-approved)."""
    data = _valid_config_dict()
    data[field] = "A|B"  # short enough to fit every field's own length bound

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-field-contains-forbidden-character"


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


def test_load_repo_config_rejects_invalid_utf8_bytes(tmp_path):
    """Resilience audit R3: adr-config.adrplus with invalid UTF-8 bytes
    raised a raw UnicodeDecodeError with EMPTY stdout in 6 different entry
    points (explore/new/approve/migrate/config/init --file), breaking the
    JSON contract. read_text(encoding="utf-8") has no default error
    handling of its own -- must be caught and turned into a CommandError,
    the same as a malformed-JSON config already is."""
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_bytes(b'{"folderadr": "doc\xffadr"}')

    with pytest.raises(CommandError) as excinfo:
        load_repo_config(config_path)

    assert excinfo.value.code == "config-invalid-encoding"
