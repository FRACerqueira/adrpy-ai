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

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


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


def test_build_header_matches_real_adrplus_output():
    """Captured byte-for-byte from a real run of the reference tool's own
    `new` command (version 1.0.0, Windows) against a disposable copy of
    this same fixture, with matching --title/--domain/--refdate arguments.

    Two deliberate divergences from that captured output:
    * The reference tool's row 2 reads literally "Values Migrated " even
      for this non-migrated file; adrpy-ai now omits the "Migrated" word
      when `migrated=False` (decision-log: accepted-divergence--2026-09-
      16--header--migrated-word-only-when-migrated.md) -- the word is
      never parsed by either tool, so the real output was misleading,
      not information adrpy-ai had to match.
    * Every status cell now carries a trailing hidden canonical marker
      (ADR004V01) the reference tool doesn't write yet -- in the same
      trailing space after the date's closing `)` both parsers already
      ignore, confirmed directly in the reference tool's own source
      (`Helper.ParseStatusLine`); a file adrpy-ai writes today is still
      readable by that tool unmodified, it just doesn't itself write the
      marker until it adopts the same convention.
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
        "|Adr-Plus Fields|Values|",
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
    """Deliberate divergence from the reference tool's own literal "Values
    Migrated" column label -- confirmed via `parse_header` below (and the
    reference tool's own positional-only parsing) that the label text is never
    read by either side, only the trailing `<!-- Migrated -->` HTML comment
    is (see decision-log:
    accepted-divergence--2026-09-16--header--migrated-word-only-when-migrated.md).
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

    assert header.split(os.linesep)[1] == "|Adr-Plus Fields|Values|"


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
    """ADR004V01's own core promise, exercised directly against
    build_header/parse_header -- deliberately NOT going through the
    `config` command (which the new existing-decisions guard would
    correctly refuse once a decision exists, exactly the scenario this
    test needs to have already happened): a decision written under one
    config must still resolve its status correctly when parsed under a
    LATER config whose statusnew/statusacc/statusrej/statussup all
    differ, including for the same status appearing in more than one row
    (created AND changed) in the same file."""
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
    """The pre-ADR004V01 file shape (any file written by an older version
    of this tool, or by AdrPlus before it adopts the same marker) has
    none -- must still resolve via the original label-text match, the
    same as before this feature existed."""
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
    marker) -- the marker remains authoritative (ADR004V01's whole point:
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
    thanks_to_the_marker above, which never set status_change at all --
    without this, the Superseded row's own marker resolution was never
    independently proven; every existing test that DOES build a
    Superseded row always reads it back under the SAME config it was
    written with, so the label fallback would silently carry it to
    green even if marker resolution broke specifically for this row."""
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
    """Every existing mismatch test elsewhere in this file
    hand-edits exactly ONE row at a time -- never two or three in the
    same file. Mutation-confirmed real gap: changing `mismatches.append(
    "status_create")` to `mismatches = ["status_create"]` (overwrite
    instead of accumulate -- exactly the shape of bug that would drop an
    earlier row's mismatch once a later row also mismatches) left the
    full suite green. Hand-edits both the Created and Changed rows'
    labels, leaving their markers untouched, and asserts BOTH survive in
    `marker_label_mismatches`, in row order."""
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
    """ADR004V02: a hand-edited marker with different case (e.g. someone
    retyped it) must still resolve via the marker, not silently fall
    back to label-text matching with zero signal -- confirmed as a real
    gap during the ADR004V01 audit. The label is deliberately corrupted
    to something no configured status matches, so `status_create` can
    ONLY come from a successful case-insensitive marker match --
    without this, the label's own unrelated match against the current
    config could resolve to the right answer by coincidence, masking a
    broken case-insensitive match entirely (confirmed: this is exactly
    what happened on the first version of this test)."""
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
    to parse. Such a header no longer counts as a family member (Round 39:
    status is read only from headers that parse); the reference tool
    counted it."""
    config = load_repo_config(FIXTURE_PATH)
    lines = [
        "<!-- Do not remove this comment, lines and table (1-12) -->",
        "|Adr-Plus Fields|Values Migrated <!-- Migrated -->|",
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
        # parse_header discriminates
        # ~15 distinct error codes, only checked via `not parsed.is_valid`
        # (or not at all) anywhere in this file -- an off-by-one that swaps
        # two adjacent branches, or collapses two into a generic code, would
        # ship undetected. One case per positional check, asserting the
        # exact code.
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
