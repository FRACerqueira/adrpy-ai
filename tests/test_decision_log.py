from pathlib import Path

from adrpy.core.decision_log import (
    build_entry_content,
    build_filename,
    decision_log_dir_for,
    next_round,
    regenerate_index,
    validate_classification,
    validate_slug,
)
from adrpy.core.errors import CommandError

import pytest


def test_decision_log_dir_for_is_a_sibling_of_the_decisions_folder():
    """Never nested inside the decisions folder -- the same structural
    reasoning that excludes the repository lock marker file from every
    decisions-folder scan (ADR003V01)."""
    result = decision_log_dir_for(Path("/repo/doc/adr"))

    assert result == Path("/repo/doc/decision-log")


def test_validate_classification_accepts_every_documented_value():
    for value in (
        "audit-finding",
        "retraction",
        "doc-drift",
        "accepted-divergence",
        "scope-note",
        "deferred",
        "risk-accepted",
        "investigation",
        "process-exception",
    ):
        validate_classification(value)  # no raise


def test_validate_classification_rejects_an_unrecognized_value():
    with pytest.raises(CommandError) as excinfo:
        validate_classification("not-a-real-classification")

    assert excinfo.value.code == "log-classification-invalid"
    assert excinfo.value.data == {"classification": "not-a-real-classification"}


@pytest.mark.parametrize(
    "slug",
    ["good-slug", "slug2", "a", "one-two-three-four"],
)
def test_validate_slug_accepts_kebab_case(slug):
    validate_slug(slug)  # no raise


@pytest.mark.parametrize(
    "slug",
    ["Not-Kebab", "trailing-", "-leading", "double--hyphen", "snake_case", "", "has space"],
)
def test_validate_slug_rejects_everything_else(slug):
    with pytest.raises(CommandError) as excinfo:
        validate_slug(slug)

    assert excinfo.value.code == "log-slug-invalid"
    assert excinfo.value.data == {"slug": slug}


def test_build_filename_matches_this_projects_own_date_first_convention():
    """This project's own established local deviation from the generic
    decision-log skill's classification-first convention -- confirmed
    against scripts/generate_decision_log_index.py's own parsing and
    every real entry in doc/decision-log/ (caught as a factual error in
    ADR003V01's first draft, fixed before implementation started)."""
    from datetime import date

    filename = build_filename(date(2026, 9, 18), "audit-finding", "lock", "some-bug")

    assert filename == "2026-09-18--audit-finding--lock--some-bug.md"


def test_build_entry_content_with_structured_line():
    content = build_entry_content(
        "A summary", "The body.", front="testing", severity="Medium", resolution="Direct", round_=3
    )

    assert content == (
        "# A summary\n\n**Front:** testing | **Severity:** Medium | **Resolution:** Direct | **Round:** 3\n\nThe body.\n"
    )


def test_build_entry_content_with_reopen_when():
    content = build_entry_content("A summary", "The body.", reopen_when="when X happens")

    assert content == "# A summary\n\n**Reopen-when:** when X happens\n\nThe body.\n"


def test_build_entry_content_with_no_structured_line():
    content = build_entry_content("A summary", "The body.")

    assert content == "# A summary\n\nThe body.\n"


def test_next_round_is_1_when_the_directory_does_not_exist_yet(tmp_path):
    assert next_round(tmp_path / "does-not-exist") == 1


def test_next_round_is_1_when_no_entry_carries_a_round(tmp_path):
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-09-18--scope-note--lock--no-round-here.md").write_text(
        "# No round here\n\nJust a note.\n", encoding="utf-8"
    )

    assert next_round(log_dir) == 1


def test_next_round_is_the_max_existing_round_plus_one_across_scopes(tmp_path):
    """Round is project-wide, never per-scope (ADR003V01/the decision-log
    skill's own definition) -- two entries under DIFFERENT scopes still
    share the same increasing sequence."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-09-18--audit-finding--lock--first.md").write_text(
        "# First\n\n**Front:** x | **Severity:** Low | **Resolution:** Direct | **Round:** 5\n\nBody.\n",
        encoding="utf-8",
    )
    (log_dir / "2026-09-18--doc-drift--config--second.md").write_text(
        "# Second\n\n**Front:** x | **Severity:** Low | **Resolution:** Direct | **Round:** 2\n\nBody.\n",
        encoding="utf-8",
    )

    assert next_round(log_dir) == 6


def test_regenerate_index_round_trips_through_next_round(tmp_path):
    """The index this function writes is itself parsed back correctly by
    next_round -- the two functions must agree on the exact structured-
    line format, not just each pass its own hand-written fixture."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-09-18--audit-finding--lock--first.md").write_text(
        build_entry_content("First", "Body.", front="x", severity="Low", resolution="Direct", round_=7),
        encoding="utf-8",
    )

    count = regenerate_index(log_dir)

    assert count == 1
    index_text = (log_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "| 2026-09-18 | audit-finding | lock | x | Low | Direct | 7 |  | First |" in index_text
    assert next_round(log_dir) == 8


def test_regenerate_index_excludes_itself_and_cycles_md(tmp_path):
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "CYCLES.md").write_text("# Cycles\n", encoding="utf-8")
    (log_dir / "2026-09-18--scope-note--lock--an-entry.md").write_text(
        build_entry_content("An entry", "Body."), encoding="utf-8"
    )

    count = regenerate_index(log_dir)

    assert count == 1
