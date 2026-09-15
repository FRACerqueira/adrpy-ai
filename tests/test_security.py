import pytest

from adrpy.core.errors import CommandError
from adrpy.core.security import reject_embedded_delimiter, resolve_within


def test_resolve_within_accepts_nested_relative_path(tmp_path):
    nested = tmp_path / "doc" / "adr"
    nested.mkdir(parents=True)

    resolved = resolve_within(tmp_path, "doc/adr")

    assert resolved == nested


def test_resolve_within_rejects_path_traversal_escape(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        resolve_within(tmp_path, "../outside")

    assert excinfo.value.code == "path-outside-repository"


def test_resolve_within_rejects_absolute_path_outside_repo(tmp_path, tmp_path_factory):
    other = tmp_path_factory.mktemp("elsewhere")

    with pytest.raises(CommandError) as excinfo:
        resolve_within(tmp_path, str(other))

    assert excinfo.value.code == "path-outside-repository"


@pytest.mark.parametrize("value", ["bad|value", "line\nbreak", "carriage\rreturn"])
def test_reject_embedded_delimiter_rejects_forbidden_characters(value):
    with pytest.raises(CommandError) as excinfo:
        reject_embedded_delimiter(value, "title")

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_reject_embedded_delimiter_accepts_clean_value():
    reject_embedded_delimiter("A normal title", "title")


@pytest.mark.parametrize(
    "char",
    ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\u0085", "\u2028", "\u2029"],
    ids=["VT", "FF", "FS", "GS", "RS", "NEL", "LS", "PS"],
)
def test_reject_embedded_delimiter_rejects_unicode_line_separators(char):
    """Security audit F4: these aren't real line terminators (confirmed
    live, see atomic_write.split_real_lines), so they no longer corrupt
    the file's line structure -- but they must still be rejected outright
    for a single-line header cell, the same as '|'/newline: a title
    silently carrying an invisible control/separator character forever is
    exactly the data-hygiene defect the original blacklist existed to
    prevent, even though its narrow (\"|\", \"\\n\", \"\\r\") list missed
    every one of these."""
    with pytest.raises(CommandError) as excinfo:
        reject_embedded_delimiter(f"before{char}after", "title")

    assert excinfo.value.code == "field-contains-forbidden-character"
