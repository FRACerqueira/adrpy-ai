from datetime import date, timedelta

import pytest

from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.lifecycle import (
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
