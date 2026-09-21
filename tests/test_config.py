import json
import sys
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


def test_folderlog_defaults_to_folderadrs_own_sibling_when_omitted():
    """ADR007V01: the concrete proof of the backward-compatibility
    promise -- an adr-config.adrplus written before folderlog existed
    (no key at all, exactly what _valid_config_dict/the shared test
    fixture already look like) must keep parsing unchanged, with
    folderlog defaulting to today's exact computed sibling location."""
    data = _valid_config_dict()
    assert "folderlog" not in data

    config = parse_repo_config(json.dumps(data))

    assert config.folderlog == "doc/decision-log"


def test_folderlog_explicit_value_is_honored():
    data = _valid_config_dict()
    data["folderlog"] = "audit-log"

    config = parse_repo_config(json.dumps(data))

    assert config.folderlog == "audit-log"


def test_folderlog_too_long_is_rejected():
    data = _valid_config_dict()
    data["folderlog"] = "d" * 51

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-folderlog-too-long"


@pytest.mark.parametrize("folderlog", [r"C:\Windows\System32", "/etc/passwd", r"C:foo"])
def test_absolute_folderlog_is_rejected(folderlog):
    data = _valid_config_dict()
    data["folderlog"] = folderlog

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-folderlog-not-relative"


@pytest.mark.parametrize(
    ("folderadr", "folderlog"),
    [
        ("doc/adr", "doc/adr"),  # equal
        ("doc/adr", "doc/adr/sub"),  # folderlog nested inside folderadr
        ("doc/adr", "doc"),  # folderadr nested inside folderlog
        ("doc/adr", "doc/other/../adr"),  # ".." traversal resolves to the same real directory
        ("doc/adr", "DOC/ADR"),  # case difference resolves to the same real directory on Windows/macOS
        pytest.param(
            r"doc\adr",
            r"doc\adr\sub",
            marks=pytest.mark.skipif(
                sys.platform != "win32", reason="backslash is only a path separator on Windows"
            ),
        ),
    ],
)
def test_overlapping_folderadr_and_folderlog_are_rejected(folderadr, folderlog):
    """ADR007V01's containment guard -- both directories are
    independently configurable and each recursively scanned, so either
    one nesting inside (or equaling) the other would make each scan see
    the other's files."""
    data = _valid_config_dict()
    data["folderadr"] = folderadr
    data["folderlog"] = folderlog

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-folderadr-folderlog-overlap"


def test_folderadr_and_folderlog_near_miss_is_accepted():
    """The required adversarial positive control for the containment
    guard: 'doc/adr' and 'doc/adr2' share a string prefix but are NOT
    nested -- compared by path component, not string prefix, so this
    must NOT trip the guard."""
    data = _valid_config_dict()
    data["folderadr"] = "doc/adr"
    data["folderlog"] = "doc/adr2"

    config = parse_repo_config(json.dumps(data))

    assert config.folderadr == "doc/adr"
    assert config.folderlog == "doc/adr2"


def test_folderlog_overlap_check_normalizes_for_comparison_only_not_storage():
    """The containment guard's host-normalization (native
    separator, ./.. collapsed, case-folded) must be comparison-only --
    the field's own STORED value stays exactly as the config text gave
    it, matching this project's established forward-slash convention,
    not whatever the current host's own path separator happens to be."""
    data = _valid_config_dict()
    data["folderadr"] = "doc/adr"
    data["folderlog"] = "doc/other/../decision-log"

    config = parse_repo_config(json.dumps(data))

    assert config.folderlog == "doc/other/../decision-log"


def test_headerdisclaimer_too_long_is_rejected():
    data = _valid_config_dict()
    data["headerdisclaimer"] = "d" * 101

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-headerdisclaimer-too-long"


def test_template_too_long_is_rejected():
    """template is the one _STRING_FIELDS field with no length
    limit at all in the schema -- unlike every other field, unbounded."""
    data = _valid_config_dict()
    data["template"] = "d" * 10_001

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-template-too-long"


def test_template_at_exactly_the_limit_is_accepted():
    data = _valid_config_dict()
    data["template"] = "d" * 10_000

    config = parse_repo_config(json.dumps(data))

    assert len(config.template) == 10_000


@pytest.mark.parametrize(
    ("field", "too_long_length"),
    [
        ("headertitlefile", 41),
        ("headerversion", 41),
        ("headerrevision", 41),
        ("headerscope", 41),
        ("headerdomain", 41),
        ("headertitlestatuscreated", 41),
        ("headertitlestatuschanged", 41),
        ("headertitlestatussuperseded", 41),
        ("headertablefields", 41),
        ("headertablevalues", 41),
        ("headermigrated", 41),
        ("statusnew", 26),
        ("statusacc", 26),
        ("statusrej", 26),
        ("statussup", 26),
    ],
)
def test_every_too_long_field_raises_its_own_matching_code(field, too_long_length):
    """ADR005V01: these 15 codes used to be built as f"config-{name}-too-long"
    at raise time; now looked up from core.config's _TOO_LONG_CODES mapping
    instead. Covers all 15 (11 header-label fields + 4 status-label fields),
    the concrete regression guard for the lookup-mapping migration itself
    (a mismatch here wouldn't show up as an import error, only as a
    silently-wrong code at runtime)."""
    data = _valid_config_dict()
    data[field] = "d" * too_long_length

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == f"config-{field}-too-long"


def test_too_long_codes_mapping_has_exactly_one_entry_per_schema_field():
    """The test above's own
    parametrize list is a hand-maintained static list -- it only
    protects fields that already have their own tuple in it. A future
    field added to the schema (and to _TOO_LONG_CODES) with no matching
    new parametrize entry would get zero test signal, surfacing only in
    production as a raw KeyError instead of a clean CommandError. This
    test derives its own expectations from the schema/registry
    themselves (not a second hand-maintained list) so it stays correct
    automatically as fields are added or removed, closing the class
    instead of the one instance."""
    from adrpy.core.config import _HEADER_LABEL_FIELDS_MAX_40, _STATUS_LABEL_FIELDS, _TOO_LONG_CODES
    from adrpy.core.errors import FailureCodes

    expected_fields = set(_HEADER_LABEL_FIELDS_MAX_40) | set(_STATUS_LABEL_FIELDS)
    assert set(_TOO_LONG_CODES.keys()) == expected_fields

    for field, code in _TOO_LONG_CODES.items():
        assert code == getattr(FailureCodes, f"CONFIG_{field.upper()}_TOO_LONG")
        assert code == f"config-{field}-too-long"


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


@pytest.mark.parametrize("field", ["statusnew", "statusacc", "statusrej", "statussup"])
@pytest.mark.parametrize(
    "payload",
    ["(20200101)<!--Rejected-->", "has(paren", "has)paren", "has<!--x", "hasx-->", "Status: Superseded"],
)
def test_status_label_with_marker_forgery_characters_is_rejected(field, payload):
    """These four fields alone land inside _parse_status_cell's own
    parenthesized-date-then-marker grammar (core/header.py) -- a label
    containing '(', ')', '<!--', or '-->' can forge a date/marker the tool
    never wrote (confirmed live: a statusnew of
    '(20200101)<!--Rejected-->' made a decision created today read back
    as Rejected/2020-01-01). ':' is also blacklisted: the Superseded row's own suffix parsing
    (`superseded_text.find(":")`, core/header.py) finds the FIRST colon
    anywhere in the cell, not necessarily the real one the tool itself
    writes after the marker -- a statussup of 'Status: Superseded'
    (19 chars, otherwise valid) made the label's own colon win instead,
    corrupting `superseded_by_file` into the whole cell remainder
    (confirmed live: `reject` on the resulting successor failed with
    superseded-predecessor-not-found even though its own primary write
    had already committed)."""
    data = _valid_config_dict()
    data[field] = payload  # short enough to fit every field's own length bound

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-field-contains-forbidden-character"


def test_header_label_fields_are_not_scoped_by_the_status_marker_forgery_check():
    """The '(' /')' half of the marker-forgery check above must stay
    scoped to the four status label fields -- header-row labels (other
    than headertablefields/headertablevalues, which get their OWN,
    narrower '<!--'/'-->' check below) are never read by
    _parse_status_cell, so a '(' in one of them is not part of that
    vulnerability's own attack surface and must still be accepted."""
    data = _valid_config_dict()
    data["headertitlestatuscreated"] = "Status (new)"

    parse_repo_config(json.dumps(data))  # must not raise


@pytest.mark.parametrize("field", ["headertablefields", "headertablevalues"])
@pytest.mark.parametrize("payload", ["Values <!-- x -->", "has<!--x", "hasx-->"])
def test_headertable_fields_with_marker_comment_characters_are_rejected(field, payload):
    """Confirmed live: parse_header's own
    is_migrated detection (core/header.py) is pure substring matching on
    the raw table-fields row -- `lines[1].rstrip().endswith(' -->|') and
    '<!-- ' in lines[1]` -- built directly from headertablefields/
    headertablevalues. Neither field was ever run through the
    marker-forgery check (only the 4 status-label fields were), so a
    hostile config setting headertablevalues to e.g. 'Values <!-- x -->'
    made is_migrated=True on the header of EVERY ordinary,
    non-migrated file ever written under that config -- confirmed live
    with an otherwise-normal `new` decision reading back as
    is_migrated: true. That flag feeds counts_as_family_member and
    several lifecycle eligibility exceptions."""
    data = _valid_config_dict()
    data[field] = payload

    with pytest.raises(CommandError) as excinfo:
        parse_repo_config(json.dumps(data))

    assert excinfo.value.code == "config-field-contains-forbidden-character"


def test_headertable_fields_still_accept_a_value_with_no_marker_comment_syntax():
    """Companion to the rejection test above: an ordinary label with no
    '<!--'/'-->' -- even one containing '(' or ')', which ISN'T part of
    this specific vulnerability's own attack surface (is_migrated
    detection only ever looks for the HTML-comment-shaped substring, not
    parentheses) -- must still be accepted."""
    data = _valid_config_dict()
    data["headertablefields"] = "Fields (raw)"
    data["headertablevalues"] = "Values"

    parse_repo_config(json.dumps(data))  # must not raise


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


def test_read_config_text_does_not_read_the_whole_file(tmp_path):
    """read_config_text (loaded on EVERY single command
    invocation, plus init/installconfig --seed) is bounded -- without
    that cap, a 150MB config file would drive a ~300MB peak-memory
    read on every single command invocation."""
    from unittest.mock import patch

    config_path = tmp_path / "adr-config.adrplus"
    huge = json.dumps(_valid_config_dict())
    huge += " " * (200 * 1024 * 1024)  # 200MB of trailing whitespace, still invalid JSON either way
    config_path.write_text(huge, encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise AssertionError("read_config_text must not read the whole file")

    with patch.object(Path, "read_text", boom), patch.object(Path, "read_bytes", boom):
        with pytest.raises(CommandError) as excinfo:
            load_repo_config(config_path)

    assert excinfo.value.code == "config-file-too-large"


def test_read_config_text_accepts_a_normal_sized_config(tmp_path):
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_text(json.dumps(_valid_config_dict()), encoding="utf-8")

    config = load_repo_config(config_path)

    assert config.folderadr == _valid_config_dict()["folderadr"]


def test_read_config_text_accepts_a_config_at_exactly_the_cap_boundary(tmp_path):
    """Positive control at the boundary itself -- a config file whose own
    JSON text is comfortably under the cap (padded with whitespace, still
    valid JSON) must parse correctly, not be treated as too-large."""
    config_path = tmp_path / "adr-config.adrplus"
    data = _valid_config_dict()
    data["template"] = "t" * config_module.TEMPLATE_MAX_LENGTH  # the field's own real max
    text = json.dumps(data)
    assert len(text.encode("utf-8")) < config_module.CONFIG_READ_MAX_BYTES  # comfortably under the cap
    config_path.write_text(text, encoding="utf-8")

    config = load_repo_config(config_path)

    assert len(config.template) == config_module.TEMPLATE_MAX_LENGTH


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

    real_open = config_module.Path.open
    calls = {"count": 0}

    def flaky_open(self, *args, **kwargs):
        calls["count"] += 1
        if calls["count"] < 3:
            raise PermissionError("Access is denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(config_module.Path, "open", flaky_open)

    config = load_repo_config(config_path)

    assert config.folderadr == "doc/adr"
    assert calls["count"] == 3
