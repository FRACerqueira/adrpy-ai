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


# Characters a shell would split on, plus the backslash (bash drops it
# outside quotes): double quotes keep these literal in bash, cmd and
# PowerShell alike.
_NEEDS_QUOTES = re.compile(r"[\s'&|;<>()*?\[\]{}^,#~\\]")
# Characters one of those shells still expands inside double quotes ($ and
# ` in bash and PowerShell, % in cmd, ! in an interactive bash) or that
# ends them ("): no single quoting keeps them literal in all three.
_UNQUOTABLE = re.compile(r"[\"$`%!]")


def shell_argument(value, placeholder="<path>"):
    """`value` as a hint shows it inside a command to copy: as is when no
    shell would change it, in double quotes when only splitting is the
    risk, and `placeholder` when a shell would expand part of it even in
    quotes -- a printed command never runs something else."""
    value = str(value)
    # A trailing backslash would escape bash's closing quote: dropped when
    # the path means the same without it, else the placeholder (a root).
    if value.endswith("\\"):
        value = value.rstrip("\\")
        if not value or value.endswith(":"):
            return placeholder
    if _UNQUOTABLE.search(value):
        return placeholder
    return f'"{value}"' if _NEEDS_QUOTES.search(value) else value
