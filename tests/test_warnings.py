from pathlib import Path

import pytest

from adrpy.core.errors import CommandError
from adrpy.core.warnings import attach_warnings, encoding_repaired_warning, orphan_cleanup_warning, retry_warning


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
    """Previously-zero-coverage branch (test-adequacy audit round 3): the
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
    """Mechanism-correctness audit round 3 (resilience finding #1): a real
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
