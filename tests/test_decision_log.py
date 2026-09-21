import os
from pathlib import Path
from unittest.mock import patch

from adrpy.core.decision_log import (
    build_entry_content,
    build_filename,
    decision_log_dir_for,
    max_existing_round,
    next_round,
    parse_round,
    regenerate_index,
    validate_classification,
    validate_resolution,
    validate_round_not_regressing,
    validate_scope,
    validate_severity,
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


def test_regenerate_index_content_matches_build_entry_contents_own_structured_line_format(tmp_path):
    """Confirms build_entry_content's own structured-line format is what
    _parse_entry/regenerate_index actually read back -- NOT a round-trip
    through regenerate_index's own output (next_round explicitly excludes
    INDEX.md from its scan, so regenerate_index's own file is never
    itself a round-trip target; this only proves build_entry_content and
    _parse_entry agree with each other, via next_round as the probe)."""
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


def test_next_round_also_excludes_itself_and_cycles_md(tmp_path):
    """Same exclusion, but for next_round's own call path (shared
    _existing_entries helper) -- regenerate_index's own test above only
    proves the OTHER caller of that helper ignores these two files."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "CYCLES.md").write_text(
        "# Cycles\n\n| Rounds | Dates | Name | Notes |\n|---|---|---|---|\n", encoding="utf-8"
    )
    (log_dir / "INDEX.md").write_text("# Decision log index\n", encoding="utf-8")
    (log_dir / "2026-09-18--audit-finding--lock--real.md").write_text(
        build_entry_content("Real", "Body.", front="x", severity="Low", resolution="Direct", round_=4),
        encoding="utf-8",
    )

    assert next_round(log_dir) == 5
    assert max_existing_round(log_dir) == 4


def test_next_round_ignores_a_non_structured_entrys_coincidentally_structured_looking_body(tmp_path):
    """_parse_entry gates the Front/Severity/Round regex match by the
    entry's OWN classification (from its filename), not attempted
    unconditionally -- a scope-note whose free-form body happens to open
    with '**Front:** ... | **Severity:** ...'-shaped prose must not be
    misread as a real structured line and skew the Round count."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-01-02--scope-note--cli--second.md").write_text(
        "# Second\n\n**Front:** narrative text | **Severity:** mentioned here | **Round:** 9\n\nrest of body\n",
        encoding="utf-8",
    )

    assert next_round(log_dir) == 1
    assert max_existing_round(log_dir) == 0


def test_max_existing_round_fails_closed_on_a_malformed_round_on_a_real_structured_entry(tmp_path):
    """A hand-written/legacy structured entry with a non-integer Round
    (scripts/generate_decision_log_index.py's own docstring anticipates
    hand-written entries) must fail closed, not be silently treated as
    carrying no Round at all -- a real structured entry's Round quietly
    not counting toward max_existing_round would let a later call
    reissue that same Round."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-01-01--audit-finding--lock--first.md").write_text(
        "# First\n\n**Front:** stability | **Severity:** High | **Resolution:** Direct | "
        "**Round:** 5 (tentative)\n\nbody\n",
        encoding="utf-8",
    )

    with pytest.raises(CommandError) as excinfo:
        max_existing_round(log_dir)
    assert excinfo.value.code == "log-directory-contains-unrecognized-file"

    with pytest.raises(CommandError) as excinfo:
        next_round(log_dir)
    assert excinfo.value.code == "log-directory-contains-unrecognized-file"


def test_max_existing_round_fails_closed_when_the_round_segment_is_entirely_missing(tmp_path):
    """Distinct from the malformed-value case above: here the structured
    line is otherwise well-formed (Front/Severity present) but the
    optional '| **Round:** ...' segment is absent entirely, not merely
    non-integer -- the malformed-value test's own Round IS present (just
    non-integer), so it never reaches this fallback (`match.group(4) or
    ""`); mutating that fallback to `match.group(4) or "0"` would pass
    every other existing test."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-01-01--audit-finding--lock--first.md").write_text(
        "# First\n\n**Front:** stability | **Severity:** High\n\nbody\n",
        encoding="utf-8",
    )

    with pytest.raises(CommandError) as excinfo:
        max_existing_round(log_dir)
    assert excinfo.value.code == "log-directory-contains-unrecognized-file"


def test_max_existing_round_fails_closed_on_a_completely_empty_file(tmp_path):
    """The `if not lines:` guard (closes a raw IndexError on `lines[0]`
    for a zero-byte decision-log file) needs its own direct test --
    confirmed by mutating the guard to `if False and not lines:` and
    observing the full suite still pass."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-01-01--audit-finding--lock--empty.md").write_text("", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        max_existing_round(log_dir)
    assert excinfo.value.code == "log-directory-contains-unrecognized-file"


def test_parse_entry_raises_a_clean_error_for_an_unrecognized_classification(tmp_path):
    """A typo'd classification (e.g. 'audit-findings') passes the
    filename-shape check (still 4 '--'-delimited segments) but must still
    fail closed: an unrecognized classification must not silently fall
    through to "no structured line", dropping a real Round that's still
    on disk from max_existing_round's own count -- the classification-
    gated regex match exists precisely to close this duplicate-Round
    risk."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-01-01--audit-finding--lock--a.md").write_text(
        build_entry_content("A", "Body.", front="x", severity="Low", resolution="Direct", round_=7),
        encoding="utf-8",
    )
    (log_dir / "2026-01-02--audit-findings--lock--b.md").write_text(
        build_entry_content("B", "Body.", front="x", severity="Low", resolution="Direct", round_=8),
        encoding="utf-8",
    )

    with pytest.raises(CommandError) as excinfo:
        max_existing_round(log_dir)
    assert excinfo.value.code == "log-directory-contains-unrecognized-file"
    assert excinfo.value.data == {"file": "2026-01-02--audit-findings--lock--b.md"}


def test_parse_entry_raises_a_clean_error_for_an_unrecognized_filename(tmp_path):
    """A stray .md file that doesn't match {date}--{classification}--
    {scope}--{slug}.md (and isn't one of the two named exceptions) must
    fail closed with a structured CommandError -- not an uncaught raw
    ValueError from path.stem.split, which would otherwise propagate
    past every caller of _existing_entries (next_round, regenerate_index)
    with no clean failure code at all."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "not-a-real-entry-name.md").write_text("nothing useful\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        next_round(log_dir)
    assert excinfo.value.code == "log-directory-contains-unrecognized-file"
    assert excinfo.value.data == {"file": "not-a-real-entry-name.md"}

    with pytest.raises(CommandError) as excinfo:
        regenerate_index(log_dir)
    assert excinfo.value.code == "log-directory-contains-unrecognized-file"


def test_parse_entry_does_not_read_the_whole_file(tmp_path):
    """A round-27 security finding: _parse_entry read the ENTIRE entry
    file (path.read_text().splitlines()) even though it only ever uses
    lines[0] (heading) and, for audit-finding/doc-drift entries,
    lines[1:5] (the structured line) -- unlike every bounded read
    elsewhere in this codebase (core/lifecycle.py's own header reads).
    No field written via `log` has a length limit (confirmed: only
    config-schema fields like folderadr/headerdisclaimer/status labels
    have _MAX_LENGTH constants -- --body/--summary/--front/--reopenwhen
    have none), so a single oversized --body persists an entry whose
    cost is then re-paid by every future `log` call scanning the whole
    directory, on every classification, not just the oversized one's
    own."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    huge_body = "x" * (2 * 1024 * 1024)  # 2MB, well past any real 5-line prefix
    (log_dir / "2026-01-01--scope-note--lock--big.md").write_text(
        build_entry_content("Big entry", huge_body), encoding="utf-8"
    )

    from pathlib import Path as PathType

    def boom(self, *args, **kwargs):
        raise AssertionError(f"_parse_entry must not read the whole file via {self!r}")

    with patch.object(PathType, "read_text", boom), patch.object(PathType, "read_bytes", boom):
        result = max_existing_round(log_dir)

    assert result == 0  # scope-note carries no Round; just proving the read stayed bounded


def test_regenerate_index_writes_lf_only_on_a_normal_successful_run(tmp_path):
    """This function's explicit LF-only convention must hold regardless
    of host OS (real, load-bearing: the committed
    doc/decision-log/INDEX.md is genuinely LF-only on disk), including on
    a normal SUCCESSFUL regeneration -- not just on the FAILURE path
    (original file untouched), which every other test of the atomic-write
    behavior already covers. Reverting atomic_write_bytes to
    atomic_write_text (which normalizes to os.linesep) would pass every
    other test in this file silently."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-09-18--scope-note--lock--first.md").write_text(
        build_entry_content("First", "Body."), encoding="utf-8"
    )

    regenerate_index(log_dir)

    assert b"\r\n" not in (log_dir / "INDEX.md").read_bytes()


def test_regenerate_index_sorts_multiple_entries_by_date_classification_scope(tmp_path):
    """Written out of both filesystem/glob and intended-display order --
    proves regenerate_index's own explicit .sort() call actually runs,
    not just that glob() happened to return them pre-sorted."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-09-18--scope-note--zzz--z-entry.md").write_text(
        build_entry_content("Z entry", "Body."), encoding="utf-8"
    )
    (log_dir / "2026-09-17--scope-note--aaa--a-entry.md").write_text(
        build_entry_content("A entry", "Body."), encoding="utf-8"
    )
    (log_dir / "2026-09-18--accepted-divergence--aaa--b-entry.md").write_text(
        build_entry_content("B entry", "Body."), encoding="utf-8"
    )

    regenerate_index(log_dir)

    index_text = (log_dir / "INDEX.md").read_text(encoding="utf-8")
    rows = [line for line in index_text.splitlines() if line.startswith("| 2026-")]
    assert [row.split("|")[9].strip() for row in rows] == ["A entry", "B entry", "Z entry"]


def test_regenerate_index_populates_the_reopen_when_column_with_real_content(tmp_path):
    """The only existing check of this column asserted it was blank (an
    audit-finding entry) -- never that a REAL deferred entry's
    Reopen-when text actually survives into the generated index."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-09-18--deferred--lock--postponed.md").write_text(
        build_entry_content("Postponed", "Body.", reopen_when="when X happens"), encoding="utf-8"
    )

    regenerate_index(log_dir)

    index_text = (log_dir / "INDEX.md").read_text(encoding="utf-8")
    assert "| deferred | lock |  |  |  |  | when X happens | Postponed |" in index_text


def test_regenerate_index_leaves_the_existing_file_untouched_when_the_atomic_write_fails(tmp_path, monkeypatch):
    """regenerate_index must go through this project's shared atomic-write
    primitive, not a plain write_text() that truncates-on-open -- a failed
    write must never leave INDEX.md empty/corrupted on disk. Simulated by
    forcing os.replace (atomic_write_bytes's own commit step) to fail
    after the temp file was written but before it replaced the real one."""
    log_dir = tmp_path / "decision-log"
    log_dir.mkdir()
    (log_dir / "2026-09-18--scope-note--lock--first.md").write_text(
        build_entry_content("First", "Body."), encoding="utf-8"
    )
    regenerate_index(log_dir)
    original = (log_dir / "INDEX.md").read_bytes()

    (log_dir / "2026-09-18--scope-note--lock--second.md").write_text(
        build_entry_content("Second", "Body."), encoding="utf-8"
    )

    def failing_replace(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(os, "replace", failing_replace)

    with pytest.raises(OSError):
        regenerate_index(log_dir)

    monkeypatch.undo()
    assert (log_dir / "INDEX.md").read_bytes() == original  # untouched, not truncated


def test_validate_scope_accepts_kebab_case():
    validate_scope("lock")
    validate_scope("install-config")


@pytest.mark.parametrize("scope", ["../../escaped", "with/slash", "with\\backslash", "double--hyphen", "Not-Kebab"])
def test_validate_scope_rejects_path_and_delimiter_unsafe_values(scope):
    """scope becomes a literal segment of the entry's filename -- '/'/'\\'
    would be read as real path separators once joined onto the
    decision-log directory, and an embedded '--' would desynchronize
    _parse_entry's own split; confirmed rejected, not just discouraged."""
    with pytest.raises(CommandError) as excinfo:
        validate_scope(scope)

    assert excinfo.value.code == "log-scope-invalid"
    assert excinfo.value.data == {"scope": scope}


def test_validate_severity_accepts_the_closed_set():
    for value in ("Low", "Medium", "High"):
        validate_severity(value)


def test_validate_severity_rejects_anything_else():
    with pytest.raises(CommandError) as excinfo:
        validate_severity("Critical")

    assert excinfo.value.code == "log-severity-invalid"


def test_validate_resolution_accepts_the_closed_set():
    for value in ("Direct", "Escalated", "Retraction"):
        validate_resolution(value)


def test_validate_resolution_rejects_anything_else():
    with pytest.raises(CommandError) as excinfo:
        validate_resolution("Maybe")

    assert excinfo.value.code == "log-resolution-invalid"


@pytest.mark.parametrize("value", ["1", "42", "1000000"])
def test_parse_round_accepts_positive_integers(value):
    assert parse_round(value) == int(value)


@pytest.mark.parametrize("value", ["0", "-1", "abc", "1.5", ""])
def test_parse_round_rejects_everything_else(value):
    with pytest.raises(CommandError) as excinfo:
        parse_round(value)

    assert excinfo.value.code == "log-round-invalid"


def test_validate_round_not_regressing_allows_reusing_the_current_max():
    validate_round_not_regressing(5, current_max=5)  # no raise


def test_validate_round_not_regressing_allows_starting_higher():
    validate_round_not_regressing(6, current_max=5)  # no raise


def test_validate_round_not_regressing_rejects_lower_than_the_current_max():
    with pytest.raises(CommandError) as excinfo:
        validate_round_not_regressing(3, current_max=5)

    assert excinfo.value.code == "log-round-too-low"
    assert excinfo.value.data == {"round": 3, "current_max": 5}


def test_validate_round_not_regressing_rejects_the_adjacent_lower_boundary():
    """The boundary case, not just a gap: every prior 'rejects lower'
    test used a gap of 2 (current_max=5, attempted=3) -- the adjacent
    value (current_max=5, attempted=4, exactly one below) needs its own
    coverage, or an off-by-one (`< current_max` vs `<= current_max - 1`,
    or similar) could ship silently."""
    with pytest.raises(CommandError) as excinfo:
        validate_round_not_regressing(4, current_max=5)

    assert excinfo.value.code == "log-round-too-low"
    assert excinfo.value.data == {"round": 4, "current_max": 5}
