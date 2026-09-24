import pytest

from adrpy.core.text import is_ascii_digits, parse_ascii_int, strip_leading_boms


@pytest.mark.parametrize("text", ["0", "007", "123"])
def test_ascii_digits_are_accepted(text):
    assert is_ascii_digits(text)


@pytest.mark.parametrize("text", ["", " 1", "1 ", "-1", "+1", "1_0", "\u0661", "\u00b2", "1a"])
def test_anything_else_is_not_ascii_digits(text):
    assert not is_ascii_digits(text)


@pytest.mark.parametrize("text, expected", [("4", 4), (" 40 ", 40), ("-3", -3), ("007", 7)])
def test_parse_ascii_int_takes_plain_integers(text, expected):
    assert parse_ascii_int(text) == expected


@pytest.mark.parametrize("text", ["", "+4", "4_0", "\u0664", "4.0", "- 4", "four"])
def test_parse_ascii_int_refuses_what_int_would_otherwise_accept_or_guess(text):
    with pytest.raises(ValueError):
        parse_ascii_int(text)


def test_strip_leading_boms_removes_only_a_leading_run():
    assert strip_leading_boms("\ufeff\ufeffa\ufeffb") == "a\ufeffb"
    assert strip_leading_boms("plain") == "plain"
