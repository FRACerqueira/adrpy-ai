from pathlib import Path

import pytest

from adrpy.core.errors import CommandError
from adrpy.core.warnings import (
    attach_warnings,
    encoding_repaired_warning,
    excluded_candidate_warning,
    orphan_cleanup_warning,
    retry_warning,
)


def test_attach_warnings_is_a_noop_on_success():
    warnings = ["a"]
    with attach_warnings(warnings):
        pass
    assert warnings == ["a"]


def test_attach_warnings_sets_warnings_when_the_error_has_none():
    warnings = ["accumulated"]
    with pytest.raises(CommandError) as excinfo:
        with attach_warnings(warnings):
            raise CommandError("boom", "detail")
    assert excinfo.value.warnings == ["accumulated"]


def test_attach_warnings_is_a_noop_when_the_error_already_carries_the_same_list():
    warnings = ["accumulated"]
    with pytest.raises(CommandError) as excinfo:
        with attach_warnings(warnings):
            raise CommandError("boom", "detail", warnings=warnings)
    assert excinfo.value.warnings is warnings
    assert excinfo.value.warnings == ["accumulated"]


def test_attach_warnings_merges_a_distinct_warnings_list_in_order():
    """Previously zero-coverage branch: the
    only production path that reaches here is a LockTimeoutError carrying
    its own reclaim warning, but the merge logic itself is independent of
    that -- any CommandError arriving with its OWN, distinct warnings list
    must have the command's own accumulated warnings prepended, not
    replaced, and in the right order."""
    warnings = ["accumulated-first", "accumulated-second"]
    with pytest.raises(CommandError) as excinfo:
        with attach_warnings(warnings):
            raise CommandError("boom", "detail", warnings=["own-warning"])
    assert excinfo.value.warnings == ["accumulated-first", "accumulated-second", "own-warning"]


def test_attach_warnings_converts_a_bare_oserror_into_a_command_error():
    """A real
    OSError from a write (permission denied, full disk, a PermissionError
    outlasting atomic_write's retry budget) used to bypass this mechanism
    entirely -- attach_warnings only caught CommandError -- propagating
    raw past every command's own accumulated warnings to __main__'s
    generic io-error with none of them attached. This is the safety net
    for every write in the wrapped region that doesn't already have its
    own tailored OSError handling (e.g. supersede's/reject's partial-
    mutation-specific `data`)."""
    warnings = ["accumulated"]
    with pytest.raises(CommandError) as excinfo:
        with attach_warnings(warnings):
            raise OSError("disk full")
    assert excinfo.value.code == "io-error"
    assert "disk full" in excinfo.value.detail
    assert excinfo.value.warnings == ["accumulated"]


def test_orphan_cleanup_warning_is_none_when_nothing_removed():
    assert orphan_cleanup_warning([]) is None


def test_orphan_cleanup_warning_names_the_removed_files():
    warning = orphan_cleanup_warning([Path("a.md.abc.tmp"), Path("b.md.def.tmp")])

    assert "a.md.abc.tmp" in warning
    assert "b.md.def.tmp" in warning
    assert "2" in warning


def test_retry_warning_is_none_for_a_single_attempt():
    assert retry_warning(1) is None
    assert retry_warning(None) is None


def test_retry_warning_names_the_attempt_count():
    assert "3" in retry_warning(3)


def test_encoding_repaired_warning_names_the_path():
    assert "decision.md" in encoding_repaired_warning("decision.md")


def test_excluded_candidate_warning_is_none_when_nothing_excluded():
    """This helper (used by
    scan_decisions/family_members/explore/init/migrate) had zero direct
    unit tests before this -- only ever exercised indirectly, and every
    one of those indirect call sites happened to use exactly one excluded
    path, so the count/pluralization/join logic was never actually
    checked against 2+."""
    assert excluded_candidate_warning([]) is None


def test_excluded_candidate_warning_names_a_single_excluded_path():
    warning = excluded_candidate_warning([Path("doc/adr/evil-junction.md")])

    assert "1 candidate file(s)" in warning
    assert "evil-junction.md" in warning


def test_excluded_candidate_warning_counts_and_joins_multiple_excluded_paths():
    """The specific gap every indirect (single-path) test left unchecked:
    the exact count matches len(paths), and multiple names are actually
    comma-joined, not overwritten/dropped."""
    warning = excluded_candidate_warning([Path("a.md"), Path("b.md"), Path("c.md")])

    assert "3 candidate file(s)" in warning
    assert "a.md" in warning
    assert "b.md" in warning
    assert "c.md" in warning
    assert "a.md, b.md, c.md" in warning
