import json

from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.header import DecisionRecord
from adrpy.core.naming import (
    build_filename,
    parse_any_filename,
    parse_filename,
    parse_legacy_filename,
    parse_migration_pattern,
)

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _config_with_migration_pattern(pattern):
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        data = json.load(f)
    data["migrationpattern"] = pattern
    return parse_repo_config(json.dumps(data))


def test_parses_a_real_adr_filename():
    config = load_repo_config(FIXTURE_PATH)

    parsed = parse_filename(
        "ADR001V01-select-adr-templates-based-on-configured-ui-language.md", config
    )

    assert parsed.number == 1
    assert parsed.version == 1
    assert parsed.revision is None
    assert parsed.prefix == "ADR"
    assert parsed.title == "select-adr-templates-based-on-configured-ui-language"


def test_parses_a_real_adr_filename_with_higher_version():
    config = load_repo_config(FIXTURE_PATH)

    parsed = parse_filename("ADR006V02-remove-scope-and-domain-specific-rules.md", config)

    assert parsed.number == 6
    assert parsed.version == 2


def test_number_width_is_not_constrained_by_config_lenseq():
    """The whole point of this parser: a file whose number has MORE digits
    than the *current* config.lenseq must still be recognized -- that's
    exactly the case the init digit-overflow check needs to catch."""
    config = load_repo_config(FIXTURE_PATH)
    assert config.lenseq == 3

    parsed = parse_filename("ADR12345V01-something.md", config)

    assert parsed.number == 12345


def test_non_matching_filename_returns_none():
    config = load_repo_config(FIXTURE_PATH)

    assert parse_filename("README.md", config) is None
    assert parse_filename("not-an-adr-file.txt", config) is None
    assert parse_filename("ADR-no-number-here.md", config) is None


def test_parse_migration_pattern_matches_the_migration_guide_example():
    """"N00:04T04" is the literal example from MigrationGuide.md, matching
    filenames like "0001UsePostgreSQL.md"."""
    pattern = parse_migration_pattern("N00:04T04")

    assert pattern == {"N": (0, 4), "T": (4, 0)}


def test_parse_migration_pattern_with_all_optional_segments():
    pattern = parse_migration_pattern("N00:04T08V04:02R06:02P12:03")

    assert pattern["N"] == (0, 4)
    assert pattern["T"] == (8, 0)
    assert pattern["V"] == (4, 2)
    assert pattern["R"] == (6, 2)
    assert pattern["P"] == (12, 3)


def test_parse_migration_pattern_rejects_malformed_text():
    assert parse_migration_pattern("") is None
    assert parse_migration_pattern("not-a-pattern") is None


def test_parses_the_migration_guide_example_filename():
    """The literal example from MigrationGuide.md's "Example: Complete
    Migration Workflow" section."""
    config = _config_with_migration_pattern("N00:04T04")

    parsed = parse_legacy_filename("0001UsePostgreSQL.md", config)

    assert parsed.number == 1
    assert parsed.version == 0
    assert parsed.revision == 0
    assert parsed.title == "UsePostgreSQL"


def test_legacy_filename_with_non_digit_sequence_is_rejected():
    config = _config_with_migration_pattern("N00:04T04")

    assert parse_legacy_filename("DECISION-001.md", config) is None


def test_legacy_filename_too_short_for_pattern_is_rejected():
    config = _config_with_migration_pattern("N00:04T04")

    assert parse_legacy_filename("001.md", config) is None


def test_legacy_scheme_is_not_recognized_when_migrationpattern_is_empty():
    config = load_repo_config(FIXTURE_PATH)
    assert config.migrationpattern == ""

    assert parse_legacy_filename("0001UsePostgreSQL.md", config) is None


def test_parses_legacy_filename_with_version_revision_and_prefix_segments():
    """Round 4 test-adequacy audit, Finding 6: every existing
    parse_legacy_filename test used only the N/T segments (the
    MigrationGuide.md pattern example) -- the V/R/P segment-extraction
    guards (length/isdigit checks) had zero coverage. Pattern below:
    N at [0:2], T at [2:], V at [4:6], R at [6:8], P at [8:10]."""
    config = _config_with_migration_pattern("N00:02T02V04:02R06:02P08:02")

    parsed = parse_legacy_filename("01XX0203AB.md", config)

    assert parsed.number == 1
    assert parsed.version == 2
    assert parsed.revision == 3
    assert parsed.prefix == "AB"
    assert parsed.title == "XX0203AB"


def test_legacy_filename_rejected_when_too_short_for_the_version_segment():
    config = _config_with_migration_pattern("N00:02T02V04:02R06:02P08:02")

    assert parse_legacy_filename("01XX.md", config) is None


def test_legacy_filename_rejected_when_version_segment_is_not_a_digit():
    config = _config_with_migration_pattern("N00:02T02V04:02R06:02P08:02")

    assert parse_legacy_filename("01XXYY03AB.md", config) is None


def test_legacy_filename_rejected_when_too_short_for_the_revision_segment():
    config = _config_with_migration_pattern("N00:02T02V04:02R06:02P08:02")

    assert parse_legacy_filename("01XX02.md", config) is None


def test_legacy_filename_rejected_when_revision_segment_is_not_a_digit():
    config = _config_with_migration_pattern("N00:02T02V04:02R06:02P08:02")

    assert parse_legacy_filename("01XX02YY.md", config) is None


def test_legacy_filename_rejected_when_too_short_for_the_prefix_segment():
    config = _config_with_migration_pattern("N00:02T02V04:02R06:02P08:02")

    assert parse_legacy_filename("01XX0203.md", config) is None


def test_parse_any_filename_prefers_current_scheme():
    config = _config_with_migration_pattern("N00:04T04")

    found = parse_any_filename(
        "ADR001V01-select-adr-templates-based-on-configured-ui-language.md", config
    )

    assert found is not None
    scheme, parsed = found
    assert scheme == "current"
    assert parsed.number == 1


def test_parse_any_filename_falls_back_to_legacy():
    config = _config_with_migration_pattern("N00:04T04")

    found = parse_any_filename("0001UsePostgreSQL.md", config)

    assert found is not None
    scheme, parsed = found
    assert scheme == "legacy"
    assert parsed.number == 1
    assert parsed.title == "UsePostgreSQL"


def test_parse_any_filename_returns_none_for_neither_scheme():
    config = _config_with_migration_pattern("N00:04T04")

    assert parse_any_filename("README.md", config) is None


def test_build_filename_matches_a_real_adr_filename():
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(
        number=1,
        title="Select ADR templates based on configured UI language",
        version=1,
    )

    filename = build_filename(config, record)

    assert filename == "ADR001V01-select-adr-templates-based-on-configured-ui-language.md"


def test_build_filename_omits_revision_when_lenrevision_is_zero():
    config = load_repo_config(FIXTURE_PATH)
    assert config.lenrevision == 0
    record = DecisionRecord(number=1, title="Some decision", version=1, revision=None)

    filename = build_filename(config, record)

    assert "R" not in filename.split("-", 1)[0][len("ADR001V01") :]


def test_build_filename_includes_revision_when_configured():
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["lenrevision"] = 2
    config = parse_repo_config(json.dumps(data))
    record = DecisionRecord(number=1, title="Some decision", version=1, revision=1)

    filename = build_filename(config, record)

    assert filename.startswith("ADR001V01R01-")


def test_build_filename_appends_supersede_suffix_unconditionally():
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(number=5, title="New decision", version=1, superseded=2)

    filename = build_filename(config, record)

    assert filename == "ADR005V01-new-decision--002.md"


def test_parse_filename_strips_supersede_suffix_and_reports_it():
    config = load_repo_config(FIXTURE_PATH)

    parsed = parse_filename("ADR005V01-new-decision--002.md", config)

    assert parsed.number == 5
    assert parsed.title == "new-decision"
    assert parsed.superseded_from == 2


def test_parse_filename_without_supersede_suffix_leaves_it_none():
    config = load_repo_config(FIXTURE_PATH)

    parsed = parse_filename("ADR001V01-select-adr-templates-based-on-configured-ui-language.md", config)

    assert parsed.superseded_from is None


def test_build_then_parse_round_trips_the_supersede_suffix():
    config = load_repo_config(FIXTURE_PATH)
    record = DecisionRecord(number=7, title="Successor decision", version=1, superseded=3)

    filename = build_filename(config, record)
    parsed = parse_filename(filename, config)

    assert parsed.number == 7
    assert parsed.superseded_from == 3
    assert parsed.title == "successor-decision"


def test_parse_filename_rejects_non_numeric_supersede_suffix():
    config = load_repo_config(FIXTURE_PATH)

    assert parse_filename("ADR005V01-new-decision--abc.md", config) is None


def test_parse_filename_rejects_more_than_one_supersede_suffix():
    config = load_repo_config(FIXTURE_PATH)

    assert parse_filename("ADR005V01-new-decision--002--003.md", config) is None
