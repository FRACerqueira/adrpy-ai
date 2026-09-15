import pytest

from adrpy.core.args import parse_flags
from adrpy.core.errors import UsageError


def test_parses_required_and_optional_flags():
    values = parse_flags(["--path", "/repo", "--title", "Hello"], required=("path", "title"), optional=("domain",))

    assert values == {"path": "/repo", "title": "Hello"}


def test_missing_required_flag_is_usage_error():
    with pytest.raises(UsageError):
        parse_flags(["--title", "Hello"], required=("path", "title"))


def test_unknown_flag_is_usage_error():
    with pytest.raises(UsageError):
        parse_flags(["--path", "/repo", "--bogus", "x"], required=("path",))


def test_flag_missing_value_is_usage_error():
    with pytest.raises(UsageError):
        parse_flags(["--path"], required=("path",))


def test_no_flags_required_or_supplied_returns_empty_dict():
    assert parse_flags([]) == {}


def test_switch_present_maps_to_true():
    values = parse_flags(["--file", "x", "--empty"], required=("file",), switches=("empty",))

    assert values == {"file": "x", "empty": True}


def test_switch_absent_is_simply_missing_from_dict():
    values = parse_flags(["--file", "x"], required=("file",), switches=("empty",))

    assert "empty" not in values


def test_switch_never_consumes_the_next_token_as_a_value():
    values = parse_flags(["--empty", "--file", "x"], required=("file",), switches=("empty",))

    assert values == {"empty": True, "file": "x"}
