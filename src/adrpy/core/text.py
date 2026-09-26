"""Small text rules shared across modules: what counts as a plain number,
and the leading BOMs an editor may add."""

import re

_PLAIN_INT = re.compile(r"-?[0-9]+")


def is_ascii_digits(text):
    """True when `text` is one or more ASCII digits and nothing else.
    str.isdigit() alone also accepts other scripts' digits and
    superscripts, which int() would then parse or reject unpredictably."""
    return text.isascii() and text.isdigit()


def ascii_digits_int(text):
    """`text` (None allowed) as an int when, once stripped, it is plain
    ASCII digits (is_ascii_digits); None otherwise, never an error -- for
    a header cell that may have been hand-edited."""
    stripped = (text or "").strip()
    return int(stripped) if is_ascii_digits(stripped) else None


def parse_ascii_int(text):
    """int() for a flag value, taking only ASCII digits with an optional
    leading '-' (surrounding spaces allowed). Plain int() also accepts other
    scripts' digits, '+4' and '4_0'; raises ValueError for those too."""
    stripped = text.strip()
    if not _PLAIN_INT.fullmatch(stripped):
        raise ValueError(f"not a plain integer: {text!r}")
    return int(stripped)


def strip_leading_boms(text):
    """The tool never writes a BOM, so any run of them at the very start
    was added by an editor (or PowerShell 5.1's -Encoding UTF8) and is not
    content -- left in, it hides what the file starts with."""
    return text.lstrip("\ufeff")
