import json

from adrpy.core.output import emit_failure

import pytest


def test_emit_failure_omits_warnings_key_when_warnings_is_none(capsys):
    """warnings=None means the run never even started accumulating (e.g.
    an OSError/internal-error caught in __main__ before any command's own
    attach_warnings region began) -- there is nothing to report, so the
    key stays absent."""
    emit_failure("some-failure", "detail")

    payload = json.loads(capsys.readouterr().out)
    assert "warnings" not in payload


def test_emit_failure_includes_an_explicitly_empty_warnings_list(capsys):
    """An explicitly empty warnings list keeps the key: every raise site that
    passes `warnings=warnings` from inside a command's attach_warnings
    region passes a REAL, already-initialized list, frequently still empty
    on a fresh run's first eligibility check. Failure responses carry
    "warnings" like success results do -- unconditionally, even empty -- so
    a generic wrapper never needs a special case."""
    emit_failure("some-failure", "detail", warnings=[])

    payload = json.loads(capsys.readouterr().out)
    assert payload["warnings"] == []


def test_emit_failure_includes_non_empty_warnings(capsys):
    emit_failure("some-failure", "detail", warnings=["something already happened"])

    payload = json.loads(capsys.readouterr().out)
    assert payload["warnings"] == ["something already happened"]



@pytest.mark.parametrize("error, expected", [
    (Exception("   "), "Exception"),
    (OSError(13, ""), "PermissionError (errno 13)"),
    (OSError(), "OSError"),
    (ValueError("real message"), "real message"),
])
def test_explain_never_returns_a_blank_or_contentless_message(error, expected):
    from adrpy.core.output import explain

    assert explain(error) == expected


def test_explain_keeps_both_filenames_when_the_message_is_empty():
    from adrpy.core.output import explain

    assert explain(OSError(17, "", "a", None, "b")) == "FileExistsError (errno 17): a -> b"
