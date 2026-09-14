import json

from adrpy.__main__ import main
from adrpy.core.output import EXIT_SUCCESS, EXIT_USAGE_ERROR


def test_help_lists_commands(capsys):
    exit_code = main(["help"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_SUCCESS
    assert payload["success"] is True
    assert any(c["name"] == "help" for c in payload["data"]["commands"])


def test_top_level_help_flag_matches_help_command(capsys):
    exit_code = main(["--help"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_SUCCESS
    assert payload["success"] is True


def test_no_arguments_matches_help_command(capsys):
    exit_code = main([])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_SUCCESS
    assert payload["success"] is True


def test_help_describes_single_command(capsys):
    exit_code = main(["help", "help"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_SUCCESS
    assert payload["data"]["commands"] == [
        {
            "name": "help",
            "description": "Lists available commands, or describes one command.",
            "arguments": [
                {
                    "name": "command",
                    "type": "string",
                    "required": False,
                    "description": "Name of the command to describe.",
                },
            ],
        }
    ]


def test_help_unknown_command_reports_structured_failure(capsys):
    from adrpy.core.output import EXIT_FAILURE

    exit_code = main(["help", "nope"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_FAILURE
    assert payload["success"] is False
    assert payload["code"] == "unknown-command"


def test_unknown_verb_is_a_usage_error(capsys):
    exit_code = main(["bogus"])
    captured = capsys.readouterr()

    assert exit_code == EXIT_USAGE_ERROR
    assert captured.out == ""
