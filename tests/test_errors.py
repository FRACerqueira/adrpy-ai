from adrpy.core.errors import CommandError, UsageError


def test_command_error_defaults_detail_data_and_warnings_to_none():
    """CommandError.__init__ had
    no direct unit test of its own -- every use in the suite is
    incidental to testing something else (a specific command's own
    behavior), never the constructor's own defaulting/fallback logic."""
    error = CommandError("some-code")

    assert error.code == "some-code"
    assert error.detail is None
    assert error.data is None
    assert error.warnings is None


def test_command_error_str_falls_back_to_the_code_when_detail_is_omitted():
    error = CommandError("some-code")

    assert str(error) == "some-code"


def test_command_error_str_uses_detail_when_given():
    error = CommandError("some-code", "a human-readable detail")

    assert str(error) == "a human-readable detail"


def test_command_error_stores_data_and_warnings_when_given():
    error = CommandError("some-code", "detail", data={"key": "value"}, warnings=["a warning"])

    assert error.data == {"key": "value"}
    assert error.warnings == ["a warning"]


def test_command_error_is_an_exception_and_carries_its_own_str_as_the_message():
    try:
        raise CommandError("boom", "it broke")
    except CommandError as error:
        assert str(error) == "it broke"
        assert isinstance(error, Exception)


def test_usage_error_is_a_distinct_exception_type():
    """Kept as a separate type from CommandError: the two map to
    different fixed exit codes (2 vs 1) -- confirms it's raisable/
    catchable on its own and isn't accidentally a CommandError subclass."""
    assert issubclass(UsageError, Exception)
    assert not issubclass(UsageError, CommandError)

    try:
        raise UsageError("bad usage")
    except UsageError as error:
        assert str(error) == "bad usage"
