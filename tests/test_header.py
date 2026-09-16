import os
from datetime import date

from adrpy.core.config import load_repo_config
from adrpy.core.header import (
    DecisionRecord,
    build_header,
    counts_as_family_member,
    parse_header,
)

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def test_build_header_matches_real_adrplus_output():
    """Captured byte-for-byte from a real `adrplus new` run (AdrPlus 1.0.0,
    Windows) against a disposable copy of this same fixture: `adrplus new
    --title "Fixture parity check" --domain "Testing" --refdate 2026-09-14`.

    One deliberate divergence from that captured output: the real tool's
    row 2 reads literally "Values Migrated " even for this non-migrated
    file; adrpy-ai now omits the "Migrated" word when `migrated=False`
    (decision-log: accepted-divergence--2026-09-16--header--migrated-word-
    only-when-migrated.md) -- the word is never parsed by either tool, so
    the real output was misleading, not information adrpy-ai had to match.
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
        "|Created|Proposed (2026-09-14)|",
        "|Changed||",
        "|Superseded||",
        "<!-- Do not remove this comment, lines and table (1-12) -->",
    ]
    assert header == os.linesep.join(expected_lines) + os.linesep


def test_build_header_label_omits_migrated_word_for_a_non_migrated_file():
    """Deliberate divergence from the real adrplus's own literal "Values
    Migrated" column label -- confirmed via `parse_header` below (and the
    real tool's own positional-only parsing) that the label text is never
    read by either side, only the trailing `<!-- Migrated -->` HTML comment
    is (see decision-log:
    accepted-divergence--2026-09-16--header--migrated-word-only-when-migrated.md).
    A non-migrated file's label no longer reads as if it had been."""
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


def test_migrated_file_counts_as_family_member_even_when_not_structurally_valid():
    """Mirrors AdrService.cs: `IsMigrated` is set from row 2 alone, before
    the rest of the header is parsed, and survives an early return caused by
    a later row failing to parse -- exactly the gap `counts_as_family_member`
    exists to cover."""
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


def test_malformed_header_is_neither_valid_nor_a_family_member():
    config = load_repo_config(FIXTURE_PATH)
    lines = ["not a header"] * 12

    parsed = parse_header(lines, config)

    assert not parsed.is_valid
    assert not counts_as_family_member(parsed)
