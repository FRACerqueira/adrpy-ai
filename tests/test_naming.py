from adrpy.core.config import load_repo_config
from adrpy.core.naming import parse_filename

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def test_parses_a_real_adr_filename():
    config = load_repo_config(FIXTURE_PATH)

    parsed = parse_filename(
        "ADR001V01-select-adr-templates-based-on-configured-ui-language.md", config
    )

    assert parsed.number == 1
    assert parsed.version == 1
    assert parsed.revision is None


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
