import json
from pathlib import Path

import pytest

from adrpy.core import config as config_module
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
    """A header/status label reaching a header table
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
def test_header_cell_field_with_whitespace_only_content_is_rejected(field):
    """`_NON_EMPTY_STRING_FIELDS`'s own check only catches a literal
    empty string (falsy) -- a whitespace-only value is truthy, so it must
    be caught separately, or it would land verbatim in a header-table
    cell, only cosmetically 'cannot be empty' as promised by this field's
    own doc/commands/config.md description. Same breadth as the sibling
    pipe-rejection test above, closing the 'only statusnew is tested for
    the empty case' asymmetry."""
    data = _valid_config_dict()
    data[field] = "   "

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-field-is-blank"


def test_field_names_are_case_insensitive():
    data = _valid_config_dict()
    data["FolderAdr"] = data.pop("folderadr")

    config = parse_repo_config(json.dumps(data))

    assert config.folderadr == "doc/adr"


@pytest.mark.parametrize(
    "pattern",
    [
        "{number}-{title}",
        "*.md",
        "T06N01:04",  # wrong order
        "N01:04",  # missing T
        "N1:4T6",  # single-digit segments
        "n01:04t06",  # lowercase
        "N01:04T06X99:99",  # unknown segment letter
        "  N01:04T06  ",  # whitespace
    ],
)
def test_invalid_migrationpattern_is_rejected(pattern):
    """Confirmed against the reference tool's own long-standing validation:
    a malformed migrationpattern must be rejected outright, not accepted
    as any string would be."""
    data = _valid_config_dict()
    data["migrationpattern"] = pattern

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-migrationpattern-invalid"


@pytest.mark.parametrize("pattern", ["", "N01:04T06", "N01:04T06V11:02R13:01P15:03"])
def test_valid_migrationpattern_is_accepted(pattern):
    data = _valid_config_dict()
    data["migrationpattern"] = pattern

    config = parse_repo_config(json.dumps(data))

    assert config.migrationpattern == pattern


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
    ],
)
def test_header_label_field_too_long_is_rejected(field):
    """Only headertitlefile was
    tested among the 11 header-label fields sharing this same 40-char
    bound -- asymmetric with the sibling embedded-delimiter check
    (test_header_cell_field_with_embedded_pipe_is_rejected above), which
    correctly parametrizes over all 16 applicable fields."""
    data = _valid_config_dict()
    data[field] = "d" * 41

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == f"config-{field}-too-long"


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
    ],
)
def test_header_label_field_at_exact_max_length_is_accepted(field):
    """No field confirmed the
    exact max value is ACCEPTED, only that max+1 is rejected -- the
    project already knows this pattern (test_valid_prefixes_are_accepted
    tests exactly PREFIX_MAX_LENGTH), just hadn't applied it here."""
    data = _valid_config_dict()
    data[field] = "d" * 40

    config = parse_repo_config(json.dumps(data))

    assert getattr(config, field) == "d" * 40


@pytest.mark.parametrize("field", ["statusnew", "statusacc", "statusrej", "statussup"])
def test_status_label_field_too_long_is_rejected(field):
    """Same asymmetry as the header-label fields above, for the 4
    status-label fields."""
    data = _valid_config_dict()
    data[field] = "d" * 26

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == f"config-{field}-too-long"


@pytest.mark.parametrize("field", ["statusnew", "statusacc", "statusrej", "statussup"])
def test_status_label_field_at_exact_max_length_is_accepted(field):
    data = _valid_config_dict()
    data[field] = "d" * 25

    config = parse_repo_config(json.dumps(data))

    assert getattr(config, field) == "d" * 25


def test_headerdisclaimer_at_exact_max_length_is_accepted():
    data = _valid_config_dict()
    data["headerdisclaimer"] = "d" * 100

    config = parse_repo_config(json.dumps(data))

    assert config.headerdisclaimer == "d" * 100


def test_folderadr_at_exact_max_length_is_accepted():
    data = _valid_config_dict()
    data["folderadr"] = "d" * 50

    config = parse_repo_config(json.dumps(data))

    assert config.folderadr == "d" * 50


@pytest.mark.parametrize(
    ("field", "value"),
    [("lenseq", 6), ("lenversion", 4), ("lenrevision", 3)],
)
def test_numeric_field_at_exact_max_is_accepted(field, value):
    data = _valid_config_dict()
    data[field] = value

    config = parse_repo_config(json.dumps(data))

    assert getattr(config, field) == value


def test_int_field_given_a_bool_is_rejected_as_wrong_type():
    """Config-wrong-type covers 4
    distinct branches (string/int/bool/list-of-strings); only the plain
    string-given-for-int case was tested. `bool` is a subtype of `int` in
    Python (`isinstance(True, int)` is True) -- config.py's own type
    check explicitly guards against this (`isinstance(value, bool) or
    not isinstance(value, int)`), otherwise `lenseq: true` would
    silently pass as `lenseq=1`."""
    data = _valid_config_dict()
    data["lenseq"] = True

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-wrong-type"


def test_string_field_given_a_wrong_type_is_rejected():
    data = _valid_config_dict()
    data["folderadr"] = 123

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-wrong-type"


def test_bool_field_given_a_wrong_type_is_rejected():
    data = _valid_config_dict()
    data["disableplugins"] = "true"  # a JSON string, not a real boolean

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-wrong-type"


def test_list_field_given_a_non_list_is_rejected():
    data = _valid_config_dict()
    data["activeplugins"] = "not-a-list"

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-wrong-type"


def test_list_field_with_a_non_string_item_is_rejected():
    data = _valid_config_dict()
    data["activeplugins"] = [1, 2]

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-wrong-type"


def test_load_repo_config_rejects_invalid_utf8_bytes(tmp_path):
    """A config file with invalid UTF-8 bytes raised a raw
    UnicodeDecodeError with EMPTY stdout in 6 different entry
    points (explore/new/approve/migrate/config/init --file), breaking the
    JSON contract. read_text(encoding="utf-8") has no default error
    handling of its own -- must be caught and turned into a CommandError,
    the same as a malformed-JSON config already is."""
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_bytes(b'{"folderadr": "doc\xffadr"}')

    with pytest.raises(CommandError) as excinfo:
        load_repo_config(config_path)

    assert excinfo.value.code == "config-invalid-encoding"


def test_load_repo_config_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """read_config_text had
    no PermissionError tolerance at all, unlike every other read in this
    codebase (core/lock.py's _read_lock, core/lifecycle.py's
    read_lines_with_report, cli/explore.py's _build_entry) -- this read
    goes through the identical atomic_write_text -> os.replace mechanism
    those retries exist to absorb, and it runs at the start of every
    single command. Reproduced empirically by the audit pass: a stress
    probe (1 writer thread, 2 reader threads, real atomic_write_text)
    measured ~0.23% of reads hitting this window -- matching the ~0.2%
    rate already measured and retried for the sibling case in
    lifecycle.py."""
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_text(json.dumps(_valid_config_dict()), encoding="utf-8")

    real_read_text = config_module.Path.read_text
    calls = {"count": 0}

    def flaky_read_text(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("Access is denied")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(config_module.Path, "read_text", flaky_read_text)

    config = load_repo_config(config_path)

    assert config.folderadr == "doc/adr"
    assert calls["count"] == 3
