import subprocess
import sys
from datetime import date, timedelta

import pytest

from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.lifecycle import (
    family_members,
    find_by_unique_title,
    next_number,
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
