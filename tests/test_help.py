import json

from adrpy.__main__ import main
from adrpy.core.output import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE_ERROR


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
                    "positional": True,
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
    """Usability audit C2: a malformed invocation must still honor the
    JSON-on-stdout contract, exit code 2 notwithstanding -- an agent
    should never need a second parser just for exit-code-2 failures."""
    exit_code = main(["bogus"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_USAGE_ERROR
    assert payload["success"] is False
    assert payload["code"] == "unknown-command"


def test_usage_error_from_a_command_still_emits_json_on_stdout(capsys):
    """Same contract, the other UsageError source: a command's own
    parse_flags (missing required argument, unknown flag) used to print
    free text to stderr with nothing at all on stdout."""
    exit_code = main(["new", "--path", "."])  # missing required --title

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_USAGE_ERROR
    assert payload["success"] is False
    assert payload["code"] == "usage-error"


def test_unhandled_oserror_still_emits_json_on_stdout(capsys, monkeypatch, tmp_path):
    """Fidelity/resilience/usability audits (independently, 3 fronts): an
    OSError not translated into a CommandError by the command itself (a
    real repro: adrpy.exe new against a path that resolves through an
    NTFS Alternate Data Stream) used to propagate as a raw traceback with
    EMPTY stdout, breaking the one contract this whole project exists to
    provide."""
    from adrpy.cli import help as help_command

    def boom(_args):
        raise OSError("simulated I/O failure")

    monkeypatch.setattr(help_command, "run", boom)

    exit_code = main(["help"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_FAILURE
    assert payload["success"] is False
    assert payload["code"] == "io-error"


def test_unhandled_generic_exception_still_emits_json_on_stdout(capsys, monkeypatch):
    """Same contract for a genuinely unexpected exception (a bug in this
    project, not an OS-level failure) -- never a raw traceback with empty
    stdout, whatever the cause."""
    from adrpy.cli import help as help_command

    def boom(_args):
        raise ValueError("simulated unexpected bug")

    monkeypatch.setattr(help_command, "run", boom)

    exit_code = main(["help"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_FAILURE
    assert payload["success"] is False
    assert payload["code"] == "internal-error"
