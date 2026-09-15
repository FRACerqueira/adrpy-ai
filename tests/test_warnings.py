from pathlib import Path

from adrpy.core.warnings import encoding_repaired_warning, orphan_cleanup_warning, retry_warning


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
