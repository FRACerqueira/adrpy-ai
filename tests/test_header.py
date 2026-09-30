import dataclasses
import os
from datetime import date

import pytest

from adrpy.core.config import load_repo_config
from adrpy.core.header import (
    DecisionRecord,
    build_header,
    parse_header,
)

FIXTURE_PATH = "tests/fixtures/.adrpy.json"


def _valid_header_lines(config):
    record = DecisionRecord(
        number=1,
        title="Baseline",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
    )
    header_text = build_header(config, record)
    return header_text.split(os.linesep)[:-1]  # drop the trailing empty split


def test_build_header_writes_the_twelve_line_header_byte_for_byte():
    """The whole header, byte for byte: the fields row holds the label
    alone, the Values label carries no "Migrated" word on a file that was
    not migrated (decision-log:
    2026-09-16--scope-note--header--migrated-word-only-when-migrated.md),
    and every status cell ends with its hidden canonical marker (ADR0004V01),
    after the date's closing `)`, where the parser ignores trailing text.
    """
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=9,
        title="Fixture parity check",
        version=1,
        domain="Testing",
        status_create="Proposed",
        date_create=date(2026, 9, 14),
    )

    header = build_header(config, record)

    expected_lines = [
        "<!-- Do not remove this comment, lines and table (1-12) -->",
        "|Fields|Values|",
        "|--|--|",
        "|File title md|Fixture parity check|",
        "|Version|01|",
        "|Revision||",
        "|Scope||",
        "|Domain|Testing|",
        "|Created|Proposed (2026-09-14) <!-- Proposed -->|",
        "|Changed||",
        "|Superseded||",
        "<!-- Do not remove this comment, lines and table (1-12) -->",
    ]
    assert header == os.linesep.join(expected_lines) + os.linesep


def test_build_header_label_omits_migrated_word_for_a_non_migrated_file():
    """The "Migrated" word appears in the Values label only on a migrated
    file -- `parse_header` never reads that label, only the trailing
    `<!-- Migrated -->` HTML comment (decision-log:
    2026-09-16--scope-note--header--migrated-word-only-when-migrated.md).
    A non-migrated file's label must not read as if it had been."""
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Not migrated",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 9, 16),
    )

    header = build_header(config, record)

    assert header.split(os.linesep)[1] == "|Fields|Values|"


def test_build_then_parse_round_trips_the_record():
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Round trip",
        version=1,
        domain="Testing",
        status_create="Proposed",
        date_create=date(2026, 9, 14),
    )

    header_text = build_header(config, record)
    lines = header_text.split(os.linesep)[:-1]  # drop the trailing empty split

    parsed = parse_header(lines, config)

    assert parsed.is_valid
    assert parsed.title == "Round trip"
    assert parsed.version == 1
    assert parsed.domain == "Testing"
    assert parsed.status_create == "Proposed"
    assert parsed.date_create == date(2026, 9, 14)
    assert not parsed.is_migrated


def test_status_still_resolves_after_every_label_changes_thanks_to_the_marker():
    """ADR0004V01's own core promise, exercised directly against
    build_header/parse_header -- deliberately NOT going through the
    `config` command (which the existing-decisions guard would correctly
    refuse once a decision exists, exactly the scenario this test needs to
    have already happened): a decision written under one config must still
    resolve its status correctly when parsed under a LATER config whose
    statusnew/statusacc/statusrej/statussup all differ, including for the
    same status appearing in more than one row (created AND changed) in
    the same file."""
    written_config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Marker survives a label change",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    header_text = build_header(written_config, record)
    lines = header_text.split(os.linesep)[:-1]  # drop the trailing empty split

    later_config = dataclasses.replace(
        written_config,
        statusnew="Something Else Entirely",
        statusacc="Yet Another Word",
        statusrej="Not Even Close",
        statussup="Completely Different",
    )
    parsed = parse_header(lines, later_config)

    assert parsed.is_valid
    assert parsed.status_create == "Proposed"
    assert parsed.date_create == date(2026, 1, 1)
    assert parsed.status_update == "Accepted"
    assert parsed.date_update == date(2026, 1, 2)
    assert parsed.marker_label_mismatches == ()  # no genuine disagreement, just a stale label


def test_status_falls_back_to_label_text_when_no_marker_is_present():
    """The pre-ADR0004V01 file shape (any file written by an older version
    of this tool, or by hand) has no marker -- its status must still
    resolve via the label-text match."""
    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    created_index = 8
    assert "<!-- Proposed -->" in lines[created_index]
    lines[created_index] = lines[created_index].replace(" <!-- Proposed -->", "")

    parsed = parse_header(lines, config)

    assert parsed.is_valid
    assert parsed.status_create == "Proposed"
    assert parsed.marker_label_mismatches == ()


def test_marker_wins_over_a_hand_edited_disagreeing_label_and_reports_the_mismatch():
    """A marker-carrying file whose VISIBLE word was hand-edited afterward
    (label now resolves to a different, but still valid, status than the
    marker) -- the marker remains authoritative (ADR0004V01's whole point:
    recognition never depends on the label once a marker exists), but
    this disagreement is real and reported, unlike the routine stale-
    label case above."""
    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    created_index = 8
    assert f"{config.statusnew} (2026-01-01) <!-- Proposed -->" in lines[created_index]
    # Hand-edit only the visible label word, leaving the hidden marker
    # (and the date) untouched -- exactly what a human editing the
    # rendered file, without touching the HTML comment, would produce.
    lines[created_index] = lines[created_index].replace(config.statusnew, config.statusacc, 1)

    parsed = parse_header(lines, config)

    assert parsed.is_valid
    assert parsed.status_create == "Proposed"  # the marker, not the now-"Accepted"-reading label
    assert parsed.marker_label_mismatches == ("status_create",)


def test_status_change_row_also_resolves_after_a_label_change_thanks_to_the_marker():
    """Companion to test_status_still_resolves_after_every_label_changes_
    thanks_to_the_marker above, which never sets status_change: every
    other test that builds a Superseded row reads it back under the SAME
    config it was written with, so the label fallback would silently carry
    it to green even if marker resolution broke specifically for this
    row."""
    written_config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Superseded row survives a label change",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
        status_change="Superseded",
        date_change=date(2026, 1, 3),
        superseded_by_file="002",
    )
    header_text = build_header(written_config, record)
    lines = header_text.split(os.linesep)[:-1]  # drop the trailing empty split

    later_config = dataclasses.replace(
        written_config,
        statusnew="Something Else Entirely",
        statusacc="Yet Another Word",
        statusrej="Not Even Close",
        statussup="Completely Different",
    )
    parsed = parse_header(lines, later_config)

    assert parsed.is_valid
    assert parsed.status_change == "Superseded"
    assert parsed.date_change == date(2026, 1, 3)
    assert parsed.superseded_by_file == "002"
    assert parsed.marker_label_mismatches == ()


def test_marker_wins_over_a_hand_edited_disagreeing_label_on_the_changed_row():
    """Same scenario as the Created-row mismatch test above, but on the
    Changed row -- _parse_status_cell is called identically at all
    three call sites inside parse_header, each appending to a shared
    mismatches list; a bug isolated to just one call site (a wrong
    literal, a copy-paste mistake) would not be caught by the
    Created-row test alone."""
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Changed row mismatch",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    header_text = build_header(config, record)
    lines = header_text.split(os.linesep)[:-1]
    changed_index = 9
    assert f"{config.statusacc} (2026-01-02) <!-- Accepted -->" in lines[changed_index]
    lines[changed_index] = lines[changed_index].replace(config.statusacc, config.statusrej, 1)

    parsed = parse_header(lines, config)

    assert parsed.is_valid
    assert parsed.status_update == "Accepted"  # the marker wins
    assert parsed.marker_label_mismatches == ("status_update",)


def test_marker_wins_over_a_hand_edited_disagreeing_label_on_the_superseded_row():
    """Same as the two tests above, on the Superseded row -- also proves
    mismatch detection isn't confused by that row's own extra
    `: <successor>` suffix trailing the marker."""
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Superseded row mismatch",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 3),
        superseded_by_file="002",
    )
    header_text = build_header(config, record)
    lines = header_text.split(os.linesep)[:-1]
    superseded_index = 10
    assert f"{config.statussup} (2026-01-03) <!-- Superseded --> : 002" in lines[superseded_index]
    # Targets "{statussup} (" specifically, not a bare .replace(config.statussup, ...) --
    # this fixture's row label (headertitlestatussuperseded) is ALSO "Superseded",
    # so a bare replace would hit the row label (leftmost) instead of the status value.
    lines[superseded_index] = lines[superseded_index].replace(f"{config.statussup} (", f"{config.statusacc} (", 1)

    parsed = parse_header(lines, config)

    assert parsed.is_valid
    assert parsed.status_change == "Superseded"  # the marker wins
    assert parsed.superseded_by_file == "002"  # successor reference still parses correctly
    assert parsed.marker_label_mismatches == ("status_change",)


def test_marker_label_mismatches_on_two_rows_simultaneously_are_both_reported():
    """Mismatches on two rows of the same file are both reported: an
    overwrite instead of an accumulate (`mismatches = ["status_create"]`
    for `mismatches.append("status_create")`) would drop an earlier row's
    mismatch once a later row also mismatches. Hand-edits both the Created
    and Changed rows' labels, leaving their markers untouched, and asserts
    BOTH survive in `marker_label_mismatches`, in row order."""
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Two simultaneous mismatches",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    header_text = build_header(config, record)
    lines = header_text.split(os.linesep)[:-1]
    created_index, changed_index = 8, 9
    assert f"{config.statusnew} (2026-01-01) <!-- Proposed -->" in lines[created_index]
    assert f"{config.statusacc} (2026-01-02) <!-- Accepted -->" in lines[changed_index]
    lines[created_index] = lines[created_index].replace(config.statusnew, config.statusrej, 1)
    lines[changed_index] = lines[changed_index].replace(config.statusacc, config.statusrej, 1)

    parsed = parse_header(lines, config)

    assert parsed.is_valid
    assert parsed.status_create == "Proposed"  # the marker wins, for both rows
    assert parsed.status_update == "Accepted"
    assert parsed.marker_label_mismatches == ("status_create", "status_update")


def test_marker_matches_case_insensitively():
    """ADR0004V02: a hand-edited marker with different case (e.g. someone
    retyped it) must still resolve via the marker, not silently fall
    back to label-text matching with zero signal. The label is deliberately
    corrupted to something no configured status matches, so
    `status_create` can ONLY come from a successful case-insensitive marker
    match -- without this, the label's own unrelated match against the
    current config could resolve to the right answer by coincidence,
    masking a broken case-insensitive match entirely."""
    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    created_index = 8
    assert f"{config.statusnew} (2026-01-01) <!-- Proposed -->" in lines[created_index]
    lines[created_index] = lines[created_index].replace(config.statusnew, "Whatever", 1)
    lines[created_index] = lines[created_index].replace("<!-- Proposed -->", "<!-- proposed -->")

    parsed = parse_header(lines, config)

    assert parsed.is_valid
    assert parsed.status_create == "Proposed"  # only resolvable via the case-insensitive marker match
    assert parsed.marker_label_mismatches == ()  # "Whatever" matches no label, so not a genuine disagreement


def test_a_damaged_migrated_header_is_marked_migrated_but_not_valid():
    """`is_migrated` is set from row 2 alone, before the rest of the header
    is parsed, and survives an early return caused by a later row failing
    to parse. Such a header no longer counts as a family member (status is
    read only from headers that parse)."""
    config = load_repo_config(FIXTURE_PATH)
    lines = [
        "<!-- Do not remove this comment, lines and table (1-12) -->",
        "|Fields|Values Migrated <!-- Migrated -->|",
        "|--|--|",
        "|File title md|Legacy decision|",
        "not a valid version row",
        "|Revision||",
        "|Scope||",
        "|Domain||",
        "|Created||",
        "|Changed||",
        "|Superseded||",
        "<!-- Do not remove this comment, lines and table (1-12) -->",
    ]

    parsed = parse_header(lines, config)

    assert parsed.is_migrated
    assert not parsed.is_valid


def _replaced(lines, index, value):
    mutated = list(lines)
    mutated[index] = value
    return mutated


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        # One case per positional check of parse_header, asserting the exact
        # code: `not parsed.is_valid` alone would let an off-by-one that swaps
        # two adjacent branches, or collapses two into a generic code, through.
        (lambda lines: [], "adr-file-empty"),
        (lambda lines: lines[:11], "adr-file-too-short"),
        (lambda lines: _replaced(lines, 0, "not a comment"), "adr-header-comment-not-found"),
        (lambda lines: _replaced(lines, 11, "not a comment"), "adr-header-comment-not-found"),
        (lambda lines: _replaced(lines, 1, "not the fields row"), "adr-header-invalid-format"),
        (lambda lines: _replaced(lines, 2, "not the separator row"), "adr-header-invalid-format"),
        (lambda lines: _replaced(lines, 3, "no pipes at all"), "adr-header-title-not-found"),
        (lambda lines: _replaced(lines, 4, "no pipes at all"), "adr-header-version-not-found"),
        (lambda lines: _replaced(lines, 4, "|Version|notadigit|"), "adr-header-version-not-found"),
        (lambda lines: _replaced(lines, 5, "no pipes at all"), "adr-header-revision-not-found"),
        (lambda lines: _replaced(lines, 5, "|Revision|notadigit|"), "adr-header-revision-not-found"),
        (lambda lines: _replaced(lines, 6, "no pipes at all"), "adr-header-scope-not-found"),
        (lambda lines: _replaced(lines, 7, "no pipes at all"), "adr-header-domain-not-found"),
        (lambda lines: _replaced(lines, 8, "no pipes at all"), "adr-header-status-created-not-found"),
        (lambda lines: _replaced(lines, 9, "no pipes at all"), "adr-header-status-updated-not-found"),
        (lambda lines: _replaced(lines, 10, "no pipes at all"), "adr-header-status-superseded-not-found"),
        (lambda lines: _replaced(lines, 10, "|Superseded|Superseded (2026-01-01)|"), "adr-status-supersede-format-invalid"),
        (lambda lines: _replaced(lines, 8, "|Created|Proposed 2026-01-01|"), "status-line-format-invalid"),
        (lambda lines: _replaced(lines, 8, "|Created|Bogus (2026-01-01)|"), "status-line-unknown-status"),
        (lambda lines: _replaced(lines, 8, "|Created|Proposed (not-a-date)|"), "status-line-date-invalid"),
    ],
    ids=[
        "file-empty",
        "file-too-short",
        "opening-comment-malformed",
        "closing-comment-malformed",
        "fields-row-malformed",
        "separator-row-malformed",
        "title-cell-unparseable",
        "version-cell-unparseable",
        "version-not-a-digit",
        "revision-cell-unparseable",
        "revision-not-a-digit",
        "scope-cell-unparseable",
        "domain-cell-unparseable",
        "created-cell-unparseable",
        "changed-cell-unparseable",
        "superseded-cell-unparseable",
        "superseded-missing-colon",
        "status-cell-missing-parens",
        "status-cell-unknown-label",
        "status-cell-invalid-date",
    ],
)
def test_parse_header_reports_the_specific_error_code(mutate, expected_code):
    config = load_repo_config(FIXTURE_PATH)
    lines = mutate(_valid_header_lines(config))

    parsed = parse_header(lines, config)

    assert parsed.error == expected_code
    assert not parsed.is_valid


def test_malformed_header_is_not_valid():
    config = load_repo_config(FIXTURE_PATH)
    lines = ["not a header"] * 12

    parsed = parse_header(lines, config)

    assert not parsed.is_valid


@pytest.mark.parametrize(
    ("row", "cell", "code"),
    [
        (3, "Use: PostgreSQL", "field-contains-forbidden-character"),
        (3, "a/b", "field-contains-forbidden-character"),
        (3, "---", "field-contains-forbidden-character"),
        (3, "", "field-contains-forbidden-character"),
        (6, "scope" + chr(0x0B) + "x", "field-contains-forbidden-character"),
        (7, "domain" + chr(0x2028) + "x", "field-contains-forbidden-character"),
    ],
)
def test_parse_header_applies_the_free_text_rules_the_commands_use(row, cell, code):
    """Title, scope and domain pass the same checks prepare() applies
    before a write (reject_embedded_delimiter; for title also the
    filesystem-unsafe and no-case-transform-content checks), so a bad
    cell makes the header itself invalid, with the rule's own code."""
    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    label = lines[row].split("|")[1]
    lines[row] = f"|{label}|{cell}|"

    result = parse_header(lines, config)

    assert result.is_valid is False
    assert result.error == code
    assert result.error_detail


def test_parse_header_keeps_scope_and_domain_optional():
    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)

    result = parse_header(lines, config)

    assert result.is_valid is True
    assert (result.scope, result.domain) == ("", "")
    assert result.error_detail is None


@pytest.mark.parametrize(
    "index, row, code",
    [
        (3, "|File title md|Baseline|extra|", "field-contains-forbidden-character"),
        (6, "|Scope|core|extra|", "field-contains-forbidden-character"),
        (7, "|Domain|db|extra|", "field-contains-forbidden-character"),
        (4, "|Version|01|02|", "adr-header-version-not-found"),
        (5, "|Revision||1|", "adr-header-revision-not-found"),
        (8, "|Created|Proposed (2026-01-01) <!-- Proposed -->|x|", "adr-header-status-created-not-found"),
        (9, "|Changed||Accepted (2026-01-02)|", "adr-header-status-updated-not-found"),
        (10, "|Superseded||x|", "adr-header-status-superseded-not-found"),
    ],
)
def test_a_header_row_with_an_extra_cell_makes_the_header_invalid(index, row, code):
    # A row is |label|value|: a third cell was silently dropped, so a
    # hand-edited value could be half lost with the header still valid.
    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    lines[index] = row

    result = parse_header(lines, config)

    assert not result.is_valid
    assert result.error == code


def test_a_header_row_without_an_extra_cell_still_parses():
    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    lines[6] = "|Scope|core|   "

    result = parse_header(lines, config)

    assert result.is_valid and result.scope == "core"



def test_the_fields_row_is_the_configured_label():
    config = load_repo_config(FIXTURE_PATH)
    assert _valid_header_lines(config)[1] == f"|{config.headertablefields}|{config.headertablevalues}|"


@pytest.mark.parametrize("row", ["|Fields|Values|", "|Legacy Fields|Values|", "|Fields |Values|"])
def test_a_fields_row_is_valid_when_its_first_cell_holds_the_label(row):
    """A header written before the row held the label alone is still
    read: the first cell only has to contain it."""
    config = load_repo_config(FIXTURE_PATH)
    assert parse_header(_replaced(_valid_header_lines(config), 1, row), config).is_valid


@pytest.mark.parametrize("row", ["|Name|Value|", "Fields|Values|", "|Values|Fields|", "|Fields"])
def test_a_fields_row_without_the_label_in_its_first_cell_is_invalid(row):
    config = load_repo_config(FIXTURE_PATH)
    parsed = parse_header(_replaced(_valid_header_lines(config), 1, row), config)
    assert parsed.error == "adr-header-invalid-format"


def test_the_fields_row_follows_the_repository_label():
    config = dataclasses.replace(load_repo_config(FIXTURE_PATH), headertablefields="Campos", headertablevalues="Valores")
    lines = _valid_header_lines(config)
    assert lines[1] == "|Campos|Valores|"
    assert parse_header(_replaced(lines, 1, "|Antigo Campos|Valores|"), config).is_valid
    assert not parse_header(_replaced(lines, 1, "|Fields|Values|"), config).is_valid


def test_a_damaged_header_is_told_apart_by_its_fields_row_alone():
    """has_header_shape tells a damaged header from none: the fields row
    alone is enough, and an ordinary markdown table is not a header."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    lines = _replaced(_valid_header_lines(config), 2, "|-|-|")
    assert has_header_shape(lines, config)
    assert not has_header_shape(["# Notes", "| Name | Value |", "|---|---|", "text"] + [""] * 8, config)


def test_a_damaged_header_in_the_older_form_is_still_a_damaged_header():
    """A fields row with more around the label in its cell is read as a
    header (parse_header); when its separator row is damaged it must stay
    a damaged header, not "no header": migrate would stack a second header
    on it and drop its status."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    lines = _replaced(_valid_header_lines(config), 1, f"|Former {config.headertablefields}|{config.headertablevalues}|")
    assert parse_header(lines, config).is_valid
    damaged = _replaced(lines, 2, "|---|---|")
    assert has_header_shape(damaged, config)
    # A hand-written table, spaces around its cells, is still no header.
    assert not has_header_shape(["# Notes", f"| {config.headertablefields} | Value |", "|---|---|"] + [""] * 9, config)
    # The wider read is the second line's only: a compact table further down
    # a legacy file, its first cell ending in the label, stays no header.
    assert not has_header_shape(["# Notes", "", "Some text.", "", f"|Custom {config.headertablefields}|Type|",
                                 "|---|---|"] + [""] * 6, config)


def test_a_note_with_a_compact_table_under_its_title_is_no_header():
    """A heading, then a table whose first cell holds the label: the fields
    row alone is not a header's shape when line 1 is not the disclaimer."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    note = ["# Form layout notes", f"|Custom {config.headertablefields}|Meaning|", "|---|---|", "|a|b|"] + [""] * 8
    assert not has_header_shape(note, config)


@pytest.mark.parametrize("comment", ["<!-- markdownlint-disable MD033 -->", "<!-- toc -->"])
def test_a_note_under_an_ordinary_comment_is_no_header(comment):
    """The older form counts only under the comment adrpy's header opens
    with, which ends in its line range: any other comment is a note's."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    note = [comment, f"|Custom {config.headertablefields}|Meaning|", "|---|---|", "|a|b|"] + [""] * 8
    assert not has_header_shape(note, config)


def test_every_source_file_compiles_without_a_warning():
    """An invalid escape in a string (a docstring's backslash before a backtick,
    say) is only a warning today and an error in a later Python."""
    import warnings
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "src" / "adrpy"
    for path in sorted(source.rglob("*.py")):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            compile(path.read_text(encoding="utf-8"), str(path), "exec")


# What prettier 3 and mdformat write for the fixture's header: a blank line
# after the comment, every cell padded to its column's width.
_FORMATTED_HEADER = [
    "<!-- Do not remove this comment, lines and table (1-12) -->",
    "",
    "| Fields        | Values                                  |",
    "| ------------- | --------------------------------------- |",
    "| File title md | Baseline                                |",
    "| Version       | 01                                      |",
    "| Revision      |                                         |",
    "| Scope         |                                         |",
    "| Domain        |                                         |",
    "| Created       | Proposed (2026-01-01) <!-- Proposed --> |",
    "| Changed       |                                         |",
    "| Superseded    |                                         |",
]


def test_a_header_a_markdown_formatter_rewrote_is_a_damaged_header():
    """An Accepted decision must not drop out of every rule because a
    formatter rewrote its header: it is adrpy's header, damaged."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    assert not parse_header(_FORMATTED_HEADER, config).is_valid
    assert has_header_shape(_FORMATTED_HEADER, config)
    assert has_header_shape(_FORMATTED_HEADER[2:] + ["", ""], config)


def test_a_header_indented_is_a_damaged_header():
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    assert has_header_shape(["    " + line for line in _valid_header_lines(config)], config)


def test_a_note_s_own_table_separator_is_no_header():
    """|--|--| under a note's own table header is the note's."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    assert not has_header_shape(["# Options", "", "|Option|Cost|", "|--|--|", "|a|1|"] + [""] * 7, config)
    assert not has_header_shape(["---", "title: x", "---", "|Name|Use|", "|--|--|"] + [""] * 7, config)
    assert not has_header_shape(["# Form", "|Form Fields|Type|", "|--|--|", "|a|b|"] + [""] * 8, config)


def test_a_note_explaining_three_header_rows_is_no_header():
    """Fewer than four rows led by a header label is a note's table, one
    that happens to talk about the same things."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    note = ["# Release notes", "", "| Item | Meaning |", "|--|--|", "| Version | the release |",
            "| Scope | what it covers |", "| Domain | who owns it |", "", "text", "", "", ""]
    assert not has_header_shape(note, config)


def _faults(lines):
    """Each way one of the first four lines can be damaged: changed,
    blanked, deleted, or pushed down by an inserted line."""
    changed = {0: "<!-- x -->", 1: "|Fiels|Values|", 2: "|---|---|", 3: "|Title|Baseline|"}
    for index in range(4):
        yield f"line {index + 1} changed", lambda ls, i=index: ls[:i] + [changed[i]] + ls[i + 1:]
        yield f"line {index + 1} blanked", lambda ls, i=index: ls[:i] + [""] + ls[i + 1:]
        yield f"line {index + 1} deleted", lambda ls, i=index: ls[:i] + ls[i + 1:] + [""]
    yield "line inserted on top", lambda ls: ["# Title"] + ls[:-1]


def test_every_single_or_double_fault_on_a_header_still_reads_as_a_damaged_header():
    """Positive controls: one or two of the top lines damaged in any way
    leave a header adrpy recognizes -- migrate must not stack a second one."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    faults = list(_faults(lines))
    for first_name, first in faults:
        assert has_header_shape(first(lines), config), first_name
        for second_name, second in faults:
            assert has_header_shape(second(first(lines)), config), (first_name, second_name)


def test_a_header_s_comment_and_separator_alone_are_still_a_damaged_header():
    """What is left of a header whose rows were all deleted: its separator
    counts on the first line, or anywhere under its own comment."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    assert has_header_shape(["|--|--|", "# damaged"], config)
    assert has_header_shape([lines[0], "", "|--|--|", "# damaged"], config)
    assert not has_header_shape(["<!-- toc -->", "|Option|Cost|", "|--|--|", "# damaged"], config)


def test_a_damaged_header_is_recognized_after_its_row_labels_were_renamed():
    """The row labels are not guarded: `config` may rename them all after a
    header was written, and that header, damaged later, must still read as
    damaged -- migrate would otherwise stack a second header on an Accepted
    decision."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(number=1, title="Baseline", version=1, status_create="Proposed",
                            date_create=date(2026, 1, 1), status_update="Accepted", date_update=date(2026, 2, 1))
    lines = build_header(config, record).split(os.linesep)[:-1]
    relabeled = dataclasses.replace(
        config, headertitlefile="Titel", headerversion="Ver", headerrevision="Rev", headerscope="Area",
        headerdomain="Team", headertitlestatuscreated="Erstellt", headertitlestatuschanged="Geaendert",
        headertitlestatussuperseded="Ersetzt")
    damaged = [f"| {config.headertablefields} | {config.headertablevalues} |"] + lines[2:] + [""]
    assert has_header_shape(damaged, relabeled)
    assert has_header_shape([line for line in lines if not line.startswith("<!--")][2:], relabeled)


def test_a_file_with_a_key_value_table_on_top_is_no_header():
    """A legacy decision or a note that opens with its own metadata table,
    rows named like the header's, is the user's: taking it for a damaged
    header would block the repository."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    note = ["# ADR 1: Use PostgreSQL", "", "| Field | Value |", "|---|---|", "| Status | Accepted |",
            "| Version | 1.0 |", "| Scope | Backend |", "| Domain | Data |", "| Created | 2024-01-01 |",
            "| Changed | 2024-02-01 |", "", "Text."]
    assert not has_header_shape(note, config)


def test_a_header_without_its_comments_or_exact_fields_row_is_still_a_damaged_header():
    """Both comment lines gone and the fields row altered: a migrated
    header's own mark, or a status marker hand-lowercased or whose date
    lost its parentheses, still tells it apart from no header."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    rows = ["|File title md|Baseline|", "|Version||", "|Revision||", "|Scope||", "|Domain||"]
    migrated = ["<!-- x -->", "|Fiels|Values Migrated <!-- Migrated -->|", "|--|--|"] + rows + ["|Created||"] * 3
    assert has_header_shape(migrated, config)
    assert has_header_shape(_replaced(migrated, 1, "| Fiels | Values Migrated <!-- Migrated --> |"), config)
    for status in ("|Created|Proposed (2026-01-01) <!-- proposed -->|", "|Created|Proposed 2026-01-01 <!-- Proposed -->|"):
        assert has_header_shape(["<!-- x -->", "| Fields | Values |", "|--|--|"] + rows + [status, "", ""], config)


def test_a_header_written_under_an_earlier_disclaimer_still_reads():
    """The disclaimer is written, never read: a header written before the
    config's disclaimer changed -- or before the default one did -- still
    parses, and still reads as damaged once damaged."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    lines = _valid_header_lines(config)
    changed = dataclasses.replace(config, headerdisclaimer="Do not edit or remove this comment, lines and table")
    assert config.headerdisclaimer != changed.headerdisclaimer
    assert parse_header(lines, changed).is_valid
    assert has_header_shape(_replaced(lines, 2, "|---|---|"), changed)


@pytest.mark.parametrize("row", [
    "| Status | Accepted <!-- 2024-01-02 --> |",
    "| Cache | Ana | decide next week <!-- follow up --> |",
    "| A | fast <!-- todo -->|",
    "| Option | Cost <!-- optional --> |",
])
def test_a_note_s_table_row_ending_in_a_comment_is_no_header(row):
    """Only the migrated fields row ends in a word and a comment holding
    that same word (`Values Migrated <!-- Migrated -->`); a note's row
    ending in a comment of its own is the note's."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    note = ["# Meeting 2026-09-30", "", "| Topic | Notes |", "|--|--|", row, "", "Text."] + [""] * 5
    assert not has_header_shape(note, config)


def test_a_migrated_fields_row_in_another_language_is_a_damaged_header():
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    lines = ["<!-- x -->", "|Campos|Valores Migrado <!-- Migrado -->|", "|--|--|", "|Titulo|x|"] + [""] * 8
    assert has_header_shape(lines, config)


@pytest.mark.parametrize("row", [
    "| Fields | Values Migrated by hand <!-- Migrated by hand --> |",
    "| Fields | Values Migrated <!-- migrated --> |",
    "|Fiels|Values Migrated (v1) <!-- Migrated (v1) -->|",
])
def test_a_migrated_fields_row_with_a_multi_word_or_recased_word_is_a_damaged_header(row):
    """headermigrated may hold spaces (the schema allows it), and a comment
    recased by hand is still the same word."""
    from adrpy.core.header import has_header_shape

    config = load_repo_config(FIXTURE_PATH)
    lines = ["# x", row, "| -- | -- |", "| File title md | x |"] + [""] * 8
    assert has_header_shape(lines, config)
