import os
import subprocess
import sys

import pytest

from adrpy.core.errors import CommandError
from adrpy.core.security import find_unreadable_subdirectories, is_within, reject_embedded_delimiter, resolve_within


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
    """is_within's own except
    (OSError, ValueError) fail-path had zero direct coverage
    -- only reached indirectly via test_lifecycle.py's Windows-junction
    test, which never exercises this branch."""
    assert is_within("some_base", "bad\x00path") is False


def test_is_within_accepts_a_precomputed_resolved_base(tmp_path):
    """resolved_base lets a caller resolve the
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
    """A NUL byte in folderadr raised a raw ValueError
    (\"embedded null character in path\") with empty stdout instead of a
    structured CommandError -- same JSON-contract violation as the other
    audit fronts' unhandled-exception findings, just a different trigger."""
    with pytest.raises(CommandError) as excinfo:
        resolve_within(tmp_path, "doc\x00adr")

    assert excinfo.value.code == "path-invalid"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_resolve_within_rejects_a_path_that_escapes_via_a_real_junction(tmp_path):
    """resolve_within's own
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


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks -- see the Windows junction test above.")
def test_resolve_within_rejects_a_path_that_escapes_via_a_real_posix_symlink(tmp_path):
    """POSIX-side counterpart to the Windows junction test above -- same
    invariant (resolve_within's own docstring claim of following real
    symlinks), a different real filesystem construct. Closes the gap
    named in decision-log: 2026-09-18--deferred--security--posix-
    symlink-escape-coverage-for-resolve-within.md -- no equivalent test
    constructed a real symlink on a POSIX host before this one. Written
    on a Windows host (this repository's own dev machine at the time)
    where it cannot be run -- creating a real Windows symlink here
    requires Developer Mode or admin privileges neither present in this
    environment (confirmed: os.symlink raised WinError 1314, "a required
    privilege is not held by the client"), so red/green for this
    specific test still needs to run on a real POSIX host or CI; it is
    at least confirmed to skip cleanly rather than error on this one."""
    base = tmp_path / "repo"
    base.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    link = base / "linked"
    link.symlink_to(outside, target_is_directory=True)

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
    """These aren't real line terminators (confirmed
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


def test_find_unreadable_subdirectories_returns_empty_when_everything_scans_fine(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "b").mkdir()

    assert find_unreadable_subdirectories(tmp_path) == []


def test_find_unreadable_subdirectories_reports_a_subdirectory_os_walk_cannot_enter(tmp_path, monkeypatch):
    """`Path.rglob` (used by every
    scan in this project) silently swallows an `OSError` raised while
    walking a subtree -- a subfolder that becomes unreadable mid-scan
    makes it return fewer results, or none, with no exception and no
    signal at all. `os.scandir` is the primitive `os.walk` (and
    `Path.rglob` internally) both build on -- monkeypatching it to deny
    one specific subdirectory reproduces the class without needing a
    real OS-level ACL setup."""
    blocked = tmp_path / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    result = find_unreadable_subdirectories(tmp_path)

    assert len(result) == 1
    assert str(blocked) in result[0]


def test_find_unreadable_subdirectories_reports_all_of_several_blocked_at_once(tmp_path, monkeypatch):
    """Every prior test here (and
    every caller's own fail-closed test) only ever blocks ONE
    subdirectory -- the accumulation behavior (does the list actually
    grow past one entry, not just fire once) was never exercised."""
    blocked_a = tmp_path / "restricted-a"
    blocked_a.mkdir()
    blocked_b = tmp_path / "restricted-b"
    blocked_b.mkdir()

    real_scandir = os.scandir
    blocked_paths = {os.path.abspath(blocked_a), os.path.abspath(blocked_b)}

    def flaky_scandir(path="."):
        if os.path.abspath(path) in blocked_paths:
            raise PermissionError(13, "Access is denied", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    result = find_unreadable_subdirectories(tmp_path)

    assert len(result) == 2
    assert any(str(blocked_a) in entry for entry in result)
    assert any(str(blocked_b) in entry for entry in result)
