import subprocess
import sys

import pytest

from adrpy.core.errors import CommandError
from adrpy.core.security import is_within, reject_embedded_delimiter, resolve_within


def test_is_within_accepts_a_candidate_inside_the_base_dir(tmp_path):
    candidate = tmp_path / "ADR001V01-decision.md"
    candidate.write_text("content", encoding="utf-8")

    assert is_within(tmp_path, candidate) is True


def test_is_within_rejects_a_candidate_that_escapes_the_base_dir(tmp_path, tmp_path_factory):
    outside = tmp_path_factory.mktemp("elsewhere")
    candidate = outside / "ADR001V01-decision.md"
    candidate.write_text("content", encoding="utf-8")

    assert is_within(tmp_path, candidate) is False


def test_is_within_returns_false_instead_of_raising_on_an_unresolvable_candidate():
    """Round 4 test-adequacy audit, Finding 7: is_within's own except
    (OSError, ValueError) fail-path (round 4 observability's own
    documented mandate: "never raises, a scan should silently treat an
    escaped candidate as outside the boundary") had zero direct coverage
    -- only reached indirectly via test_lifecycle.py's Windows-junction
    test, which never exercises this branch."""
    assert is_within("some_base", "bad\x00path") is False


def test_is_within_accepts_a_precomputed_resolved_base(tmp_path):
    """Round 4 performance front: resolved_base lets a caller resolve the
    base directory once outside a scan loop instead of once per
    candidate -- must produce the exact same result as the default,
    resolve-it-yourself path."""
    candidate = tmp_path / "ADR001V01-decision.md"
    candidate.write_text("content", encoding="utf-8")

    assert is_within(tmp_path, candidate, resolved_base=tmp_path.resolve()) is True

    outside_base = tmp_path / "not-actually-the-real-base"
    assert is_within(tmp_path, candidate, resolved_base=outside_base) is False


def test_resolve_within_accepts_nested_relative_path(tmp_path):
    nested = tmp_path / "doc" / "adr"
    nested.mkdir(parents=True)

    resolved = resolve_within(tmp_path, "doc/adr")

    assert resolved == nested


def test_resolve_within_rejects_path_traversal_escape(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        resolve_within(tmp_path, "../outside")

    assert excinfo.value.code == "path-outside-repository"


def test_resolve_within_rejects_nul_byte_in_candidate(tmp_path):
    """Security audit F5: a NUL byte in folderadr raised a raw ValueError
    (\"embedded null character in path\") with empty stdout instead of a
    structured CommandError -- same JSON-contract violation as the other
    audit fronts' unhandled-exception findings, just a different trigger."""
    with pytest.raises(CommandError) as excinfo:
        resolve_within(tmp_path, "doc\x00adr")

    assert excinfo.value.code == "path-invalid"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_resolve_within_rejects_a_path_that_escapes_via_a_real_junction(tmp_path):
    """Round 4 test-adequacy audit, Finding 9: resolve_within's own
    docstring claims it follows real symlinks when resolving ("real path
    resolution (following `..` and symlinks)") -- no existing test
    constructed an actual symlink/junction against this function
    directly, only indirectly via is_within/scan_decisions
    (test_lifecycle.py's own junction test targets a different
    function)."""
    base = tmp_path / "repo"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    junction = base / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    with pytest.raises(CommandError) as excinfo:
        resolve_within(base, "linked/escaped.md")

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
