import pytest

from adrpy.core.text import ascii_digits_int, is_ascii_digits, parse_ascii_int, strip_leading_boms


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


@pytest.mark.parametrize("text, expected", [("3", 3), (" 007 ", 7)])
def test_ascii_digits_int_takes_ascii_digits_around_spaces(text, expected):
    assert ascii_digits_int(text) == expected


@pytest.mark.parametrize("text", [None, "", "  ", "-3", "+3", "3_0", "²", "٢", "two"])
def test_ascii_digits_int_is_none_for_anything_else(text):
    assert ascii_digits_int(text) is None


def test_strip_leading_boms_removes_only_a_leading_run():
    assert strip_leading_boms("\ufeff\ufeffa\ufeffb") == "a\ufeffb"
    assert strip_leading_boms("plain") == "plain"


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        (".", "."),
        ("doc/adr", "doc/adr"),
        ("my repo", '"my repo"'),
        ("C:\\Users\\me\\repo", '"C:\\Users\\me\\repo"'),
        ("a&b", '"a&b"'),
    ],
)
def test_shell_argument_quotes_only_what_needs_it(value, shown):
    from adrpy.core.text import shell_argument

    assert shell_argument(value) == shown


@pytest.mark.parametrize("value", ['a"b', "C:\\x$y", "a`b", "%TEMP%\\repo", "/tmp/$(touch pwned)/repo", "a!b"])
def test_shell_argument_never_prints_a_value_a_shell_would_expand_even_in_quotes(value):
    # No single quoting keeps these literal in bash, cmd and PowerShell
    # alike: the hint shows the placeholder instead of a command that could
    # run something else.
    from adrpy.core.text import shell_argument

    assert shell_argument(value, "<path>") == "<path>"
