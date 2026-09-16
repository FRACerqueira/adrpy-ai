import json

from adrpy.__main__ import main
from adrpy.core.output import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE_ERROR
from adrpy.core.registry import COMMANDS


_LOCKED_COMMANDS = ("new", "approve", "reject", "undo", "supersede", "version", "revise", "migrate", "config", "init")
_PER_FILE_COMMANDS = ("approve", "reject", "undo", "supersede", "version", "revise")


def test_every_locked_command_documents_repository_locked():
    """Round 5 stability re-run, Usability Finding 1: repository-locked/
    lock-lost are the ADR001-designed failure boundary for every command
    that acquires the repository lock, but were undocumented anywhere on
    the caller-facing describe() surface -- an agent had no way to learn
    these codes exist short of reading core/lock.py's own source. Checks
    every description string in describe() (top-level and each
    argument's own), not just the top-level one, since init's own note
    lives on its --seed argument, scoped to the already-existing-
    repository path only."""
    for name in _LOCKED_COMMANDS:
        info = COMMANDS[name].describe()
        text = info["description"] + " ".join(arg.get("description", "") for arg in info.get("arguments", []))
        assert "repository-locked" in text, f"{name}'s describe() never mentions repository-locked"


def test_every_locked_command_documents_folderadr_changed_after_lock_acquired():
    """Round 6 calibration, usability finding: folderadr-changed-after-
    lock-acquired (core.lifecycle.verify_folderadr_unchanged_since_lock,
    used by all 9 write commands plus init's --seed-on-existing-repo
    path) was introduced by round 6's own shared fix but never
    documented in any describe() -- found by the calibration process
    itself (a grep) before proposing round 7, not by a dedicated
    audit pass."""
    for name in _LOCKED_COMMANDS:
        info = COMMANDS[name].describe()
        text = info["description"] + " ".join(arg.get("description", "") for arg in info.get("arguments", []))
        assert "folderadr-changed-after-lock-acquired" in text, f"{name}'s describe() never mentions it"


def test_config_and_init_document_folderadr_change_scan_incomplete():
    """Round 6 calibration, usability finding: folderadr-change-scan-
    incomplete (core.lifecycle.reject_folderadr_change_if_decisions_exist's
    own fail-closed path) is only reachable from config and init (the
    only two callers of that guard), also introduced by round 6 and also
    undocumented until now."""
    for name in ("config", "init"):
        info = COMMANDS[name].describe()
        text = info["description"] + " ".join(arg.get("description", "") for arg in info.get("arguments", []))
        assert "folderadr-change-scan-incomplete" in text, f"{name}'s describe() never mentions it"


def test_every_per_file_command_documents_the_md_auto_suffix():
    """Round 5 usability re-run, Finding 7 (pre-existing, minor): every
    per-file command's `--file` silently gets '.md' appended when the
    given path has no extension (resolve_repo_and_target's own doing) --
    none of their describe()'s ever mentioned it."""
    for name in _PER_FILE_COMMANDS:
        info = COMMANDS[name].describe()
        file_arg = next(arg for arg in info["arguments"] if arg["name"] == "file")
        assert ".md" in file_arg["description"], f"{name}'s --file description never mentions the .md suffix"


def test_help_lists_commands(capsys):
    exit_code = main(["help"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_SUCCESS
    assert payload["success"] is True
    assert any(c["name"] == "help" for c in payload["data"]["commands"])
    # Usability audit round 3 (finding #5): "warnings" is present
    # unconditionally on every other command's result, even when empty --
    # help omitted it entirely, breaking a generic wrapper that assumed
    # the key always exists.
    assert payload["data"]["warnings"] == []


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


def test_command_error_can_carry_structured_data_on_failure(capsys, monkeypatch):
    """Usability audit: some failures need more than a code and a stderr-
    only detail string to be actionable -- not-latest-version, for
    instance, needs to name WHICH version actually is the latest. A
    CommandError should be able to carry that as real JSON data, not a
    number buried in free text."""
    from adrpy.cli import help as help_command
    from adrpy.core.errors import CommandError

    def boom(_args):
        raise CommandError("some-failure", "human-readable detail", data={"latest_version": 3})

    monkeypatch.setattr(help_command, "run", boom)

    exit_code = main(["help"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_FAILURE
    assert payload["code"] == "some-failure"
    assert payload["data"] == {"latest_version": 3}


def test_command_error_can_carry_warnings_on_failure(capsys, monkeypatch):
    """Mechanism-correctness audit round 2: a real side effect (an encoding
    repair, an orphan-temp-file cleanup, a stale-lock reclaim, a retried
    write) that already happened before a command goes on to fail for an
    unrelated reason used to be silently dropped -- the failure envelope
    carried no trace that anything had already occurred."""
    from adrpy.cli import help as help_command
    from adrpy.core.errors import CommandError

    def boom(_args):
        raise CommandError("some-failure", "human-readable detail", warnings=["something already happened"])

    monkeypatch.setattr(help_command, "run", boom)

    exit_code = main(["help"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_FAILURE
    assert payload["code"] == "some-failure"
    assert payload["warnings"] == ["something already happened"]


def test_command_error_includes_an_explicitly_empty_warnings_list(capsys, monkeypatch):
    """Round 4 (observability audit Finding 4 / test-adequacy audit
    Finding 4): distinct from the "no warnings" case below -- warnings=[]
    means a command's own attach_warnings region genuinely started
    accumulating and just had nothing to report yet, not "nothing to
    report at all". See core/output.py's own emit_failure fix."""
    from adrpy.cli import help as help_command
    from adrpy.core.errors import CommandError

    def boom(_args):
        raise CommandError("some-failure", "human-readable detail", warnings=[])

    monkeypatch.setattr(help_command, "run", boom)

    exit_code = main(["help"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_FAILURE
    assert payload["code"] == "some-failure"
    assert payload["warnings"] == []


def test_command_error_omits_warnings_key_when_there_are_none(capsys, monkeypatch):
    from adrpy.cli import help as help_command
    from adrpy.core.errors import CommandError

    def boom(_args):
        raise CommandError("some-failure", "human-readable detail")

    monkeypatch.setattr(help_command, "run", boom)

    exit_code = main(["help"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_FAILURE
    assert "warnings" not in payload


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
