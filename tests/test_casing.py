import pytest

from adrpy.core.casing import to_camel_case, to_case, to_kebab_case, to_pascal_case, to_snake_case, unique_title_key
from adrpy.core.config import load_repo_config

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "helloWorld"),
        ("hello-world", "helloWorld"),
        ("HelloWorld", "helloWorld"),
        ("XMLParser", "xmlParser"),
    ],
)
def test_to_camel_case(text, expected):
    assert to_camel_case(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "HelloWorld"),
        ("hello-world", "HelloWorld"),
        ("hello_world", "HelloWorld"),
        ("XMLParser", "XmlParser"),
    ],
)
def test_to_pascal_case(text, expected):
    assert to_pascal_case(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "hello_world"),
        ("HelloWorld", "hello_world"),
        ("hello-world", "hello_world"),
    ],
)
def test_to_snake_case(text, expected):
    assert to_snake_case(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hello World", "hello-world"),
        ("HelloWorld", "hello-world"),
        ("hello_world", "hello-world"),
        (
            "select adr templates based on configured ui language",
            "select-adr-templates-based-on-configured-ui-language",
        ),
    ],
)
def test_to_kebab_case(text, expected):
    assert to_kebab_case(text) == expected


def test_to_case_dispatches_by_config_format():
    assert to_case("Hello World", "KebabCase") == "hello-world"
    assert to_case("Hello World", "SnakeCase") == "hello_world"
    assert to_case("Hello World", "PascalCase") == "HelloWorld"
    assert to_case("Hello World", "CamelCase") == "helloWorld"


def test_unique_title_key_normalizes_regardless_of_input_casing():
    config = load_repo_config(FIXTURE_PATH)
    assert config.casetransform == "KebabCase"

    key_from_prose = unique_title_key("Use PostgreSQL Database", config)
    key_from_filename_style = unique_title_key("use-postgre-sql-database", config)

    assert key_from_prose == key_from_filename_style == "UsePostgreSqlDatabase"
