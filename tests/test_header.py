import dataclasses
import os
from datetime import date

import pytest

from adrpy.core.config import load_repo_config
from adrpy.core.header import (
    DecisionRecord,
    build_header,
    counts_as_family_member,
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
    assert counts_as_family_member(parsed)
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


def test_migrated_file_counts_as_family_member_even_when_not_structurally_valid():
    """Matches the reference tool's own behavior: `is_migrated` is set from
    row 2 alone, before the rest of the header is parsed, and survives an
    early return caused by a later row failing to parse -- exactly the gap
    `counts_as_family_member` exists to cover."""
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
    assert counts_as_family_member(parsed)


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


def test_malformed_header_is_neither_valid_nor_a_family_member():
    config = load_repo_config(FIXTURE_PATH)
    lines = ["not a header"] * 12

    parsed = parse_header(lines, config)

    assert not parsed.is_valid
    assert not counts_as_family_member(parsed)
