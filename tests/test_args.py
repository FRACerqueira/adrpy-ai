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


def test_short_flag_alias_is_equivalent_to_the_long_flag():
    """Fidelity audit F10: the real adrplus documents a short alias for
    every argument on every command (-p/--path, -t/--title, ...); adrpy
    only ever accepted the long form."""
    values = parse_flags(
        ["-p", "/repo", "-t", "Hello"],
        required=("path", "title"),
        aliases={"p": "path", "t": "title"},
    )

    assert values == {"path": "/repo", "title": "Hello"}


def test_short_flag_alias_works_for_a_switch():
    values = parse_flags(
        ["-f", "x", "-e"],
        required=("file",),
        switches=("empty",),
        aliases={"f": "file", "e": "empty"},
    )

    assert values == {"file": "x", "empty": True}


def test_unknown_short_flag_is_usage_error():
    with pytest.raises(UsageError):
        parse_flags(["-z", "x"], required=("path",), aliases={"p": "path"})


def test_flag_with_empty_string_value_is_usage_error():
    """Fidelity audit F5: confirmed live -- `adrplus new --title ""`
    refuses with "Missing value for argument", the same class of failure
    as omitting the flag entirely. adrpy accepted an empty string as a
    real value, which for --domain/--scope on `version` even let an
    omitted-vs-explicitly-cleared distinction do something the real tool
    has no way to express (erasing an inherited value)."""
    with pytest.raises(UsageError):
        parse_flags(["--title", ""], required=("title",))


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
