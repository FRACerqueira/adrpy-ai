import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, HeaderParseResult, build_header
from adrpy.core.lifecycle import (
    family_members,
    find_by_unique_title,
    ineligibility_reason_for_approve_or_reject,
    ineligibility_reason_for_supersede,
    ineligibility_reason_for_undo,
    ineligibility_reason_for_version_or_revise,
    load_target,
    next_number,
    read_header_lines,
    rewrite_status_field,
    scan_decisions,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
)

import json

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def test_validate_refdate_not_in_future_accepts_today():
    validate_refdate_not_in_future(date.today())


def test_validate_refdate_not_in_future_rejects_tomorrow():
    with pytest.raises(CommandError) as excinfo:
        validate_refdate_not_in_future(date.today() + timedelta(days=1))

    assert excinfo.value.code == "refdate-in-future"


def test_validate_refdate_not_before_accepts_same_day():
    validate_refdate_not_before(date(2026, 1, 1), date(2026, 1, 1))


def test_validate_refdate_not_before_rejects_earlier_date():
    with pytest.raises(CommandError) as excinfo:
        validate_refdate_not_before(date(2026, 1, 1), date(2026, 1, 2))

    assert excinfo.value.code == "refdate-before-history"


def test_next_number_is_one_when_no_decisions_exist(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    assert next_number(scan_decisions(tmp_path, config)) == 1


def test_next_number_and_unique_title_with_real_decisions(tmp_path):
    config_dict = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=3, title="Existing decision", version=1)
    with open(adr_dir / "ADR003V01-existing-decision.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    decisions = scan_decisions(adr_dir, config)

    assert next_number(decisions) == 4
    assert find_by_unique_title("Existing Decision", config, decisions) is not None
    assert find_by_unique_title("Existing decision", config, decisions) is not None
    assert find_by_unique_title("Totally different", config, decisions) is None


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ("", "adr-file-empty"),
        ("|only one line|", "adr-file-too-short"),
    ],
)
def test_load_target_surfaces_the_specific_header_error_as_the_code(tmp_path, content, expected_code):
    """Usability audit A4: header.error is already a specific, correctly-
    computed reason (adr-file-empty, adr-header-title-not-found, ...);
    load_target discarded it behind a single fixed "header-invalid" code,
    forcing an agent to fall back to a stderr string it can't rely on."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    target = adr_dir / "ADR001V01-broken.md"
    target.write_text(content, encoding="utf-8")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        load_target(target)

    assert excinfo.value.code == expected_code


def test_load_target_reports_no_encoding_repair_for_a_clean_file(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Clean", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-clean.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body\n")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    *_rest, encoding_repaired = load_target(target)

    assert encoding_repaired is False


def test_load_target_reports_encoding_repair_when_body_has_invalid_utf8_bytes(tmp_path):
    """Observability audit: reading a file with invalid UTF-8 bytes (Fase
    4: tolerated, confirmed live to match the real tool) silently replaces
    them with U+FFFD -- nothing told the caller this happened, even though
    it's a real, permanent loss of the original bytes the moment the file
    is rewritten."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Dirty", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-dirty.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body\n")
    with open(target, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    *_rest, encoding_repaired = load_target(target)

    assert encoding_repaired is True


def test_rewrite_status_field_returns_the_write_attempt_count(tmp_path):
    """Observability audit: rewrite_status_field discarded atomic_write_text's
    own attempt count -- callers (approve/reject/undo) had no way to
    surface a "this needed retries" warning."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-existing.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    from adrpy.core.header import parse_header
    from adrpy.core.lifecycle import read_lines
    from adrpy.core.naming import parse_any_filename

    lines = read_lines(target)
    header = parse_header(lines, config)
    _, filename_info = parse_any_filename(target.name, config)

    _record, _content, attempts = rewrite_status_field(
        target, config, lines, header, filename_info, field="update", status="Accepted", refdate=date(2026, 1, 2)
    )

    assert attempts == 1


def _header(**overrides):
    defaults = dict(is_valid=True, status_create="Proposed", status_update=None, status_change=None)
    defaults.update(overrides)
    return HeaderParseResult(**defaults)


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": None}, None),
        ({"status_update": "Accepted"}, "already-accepted"),
        ({"status_update": "Rejected"}, "already-rejected"),
        ({"status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted"}, "not-proposed"),
    ],
)
def test_ineligibility_reason_for_approve_or_reject(header_kwargs, expected_reason):
    """Usability audit: replaces a single collapsed not-eligible-for-*
    boolean with the SPECIFIC observed state -- an agent needs to know
    whether a decision is already accepted, already rejected, or already
    superseded, since each calls for a different recovery action."""
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_approve_or_reject(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": "Rejected"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
    ],
)
def test_ineligibility_reason_for_undo(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_undo(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Rejected"}, "already-rejected"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
    ],
)
def test_ineligibility_reason_for_supersede(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_supersede(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": "Rejected"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
    ],
)
def test_ineligibility_reason_for_version_or_revise(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_version_or_revise(header) == expected_reason


def test_read_header_lines_does_not_read_the_whole_file(tmp_path):
    """Performance backlog item: family_members only ever needs the fixed
    12-line header to decide membership -- reading a potentially huge
    body just for that is wasted I/O, repeated for every sibling on every
    lifecycle check (approve/reject/undo/version/revise/supersede)."""
    header_lines = [f"line{i}" for i in range(12)]
    huge_body = "x" * (5 * 1024 * 1024)
    target = tmp_path / "big.md"
    target.write_text("\n".join(header_lines) + "\n" + huge_body, encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise AssertionError("read_header_lines must not read the whole file")

    with patch.object(Path, "read_text", boom), patch.object(Path, "read_bytes", boom):
        lines = read_header_lines(target, count=12)

    assert lines == header_lines


def test_read_header_lines_handles_a_file_shorter_than_the_header(tmp_path):
    target = tmp_path / "short.md"
    target.write_text("only\ntwo\n", encoding="utf-8")

    lines = read_header_lines(target, count=12)

    assert lines == ["only", "two"]


def test_family_members_excludes_a_structurally_invalid_file(tmp_path):
    """Legacy-scheme census audit: family_members must apply
    counts_as_family_member (is_valid OR is_migrated), mirroring
    AdrService.ReadAllAdrByNumber -- a filename-matching file whose header
    doesn't parse at all (unmigrated legacy, or simply corrupt) must never
    be counted as a family member, regardless of which naming scheme
    matched its filename."""
    config_dict = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    config_dict["migrationpattern"] = "N00:04T04"
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing decision", version=1, status_create="Proposed")
    with open(adr_dir / "ADR001V01-existing-decision.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    (adr_dir / "0001LegacyNotes.md").write_text("# Not a real header at all\n", encoding="utf-8")

    members = family_members(adr_dir, config, 1)

    assert len(members) == 1
    assert members[0][0].title == "existing-decision"


def test_scan_decisions_never_sees_the_lock_marker_file(tmp_path):
    """Harness Fase 4/6/7 requirement (flagged by the resilience audit as
    unchecked by any front): LOCK_FILE_NAME must never appear as an
    "unrecognized file" nor be mistaken for a naming-scheme candidate.
    Confirmed here as an explicit guarantee, not an accident of every
    rglob call happening to filter on "*.md" -- if that filter ever
    changed, this is the test that would catch a regression."""
    from adrpy.core.lock import LOCK_FILE_NAME

    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    (adr_dir / LOCK_FILE_NAME).write_text("holder-token\n123.0")

    assert scan_decisions(adr_dir, config) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_scan_decisions_ignores_files_reached_through_a_windows_junction(tmp_path):
    """Security audit F2: resolve_within only validates the repository
    root; rglob("*.md") happily descends into a Windows junction planted
    inside the decisions folder (no admin privilege required to create
    one, and Path.is_symlink() does NOT detect it). Confirmed live:
    `migrate` wrote a real AdrPlus header into a file OUTSIDE the repo
    through exactly this, and `next_number` was poisoned by the outside
    file's own (unrelated) sequence number."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / "repo" / config.folderadr
    adr_dir.mkdir(parents=True)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    record = DecisionRecord(number=9, title="Victim outside the repo", version=1)
    with open(outside_dir / "ADR009V01-victim-outside-the-repo.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not junction.is_symlink()  # confirms the audit's premise: junctions aren't symlinks

    decisions = scan_decisions(adr_dir, config)

    assert decisions == []
    assert next_number(decisions) == 1
