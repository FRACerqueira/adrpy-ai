import json

from adrpy.__main__ import main
from adrpy.core.output import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE_ERROR
from adrpy.core.registry import COMMANDS

import pytest


_LOCKED_COMMANDS = ("new", "approve", "reject", "undo", "supersede", "version", "revise", "migrate", "config", "init", "log")
_PER_FILE_COMMANDS = ("approve", "reject", "undo", "supersede", "version", "revise")


def test_every_locked_command_documents_repository_locked():
    """Repository-locked/
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
    """Folderadr-changed-after-
    lock-acquired (core.lifecycle.verify_folderadr_unchanged_since_lock,
    used by all 9 write commands plus init's --seed-on-existing-repo
    path) was a shared fix never documented in any describe() -- found
    by the calibration process itself (a grep), not by a dedicated
    audit pass."""
    for name in _LOCKED_COMMANDS:
        info = COMMANDS[name].describe()
        text = info["description"] + " ".join(arg.get("description", "") for arg in info.get("arguments", []))
        assert "folderadr-changed-after-lock-acquired" in text, f"{name}'s describe() never mentions it"


def test_config_and_init_document_folderadr_change_scan_incomplete():
    """Folderadr-change-scan-
    incomplete (core.lifecycle.reject_folderadr_change_if_decisions_exist's
    own fail-closed path) is only reachable from config and init (the
    only two callers of that guard), and was also undocumented until
    now."""
    for name in ("config", "init"):
        info = COMMANDS[name].describe()
        text = info["description"] + " ".join(arg.get("description", "") for arg in info.get("arguments", []))
        assert "folderadr-change-scan-incomplete" in text, f"{name}'s describe() never mentions it"


def test_new_supersede_and_version_document_the_forbidden_character_constraint():
    """reject_embedded_
    delimiter (core/security.py) is enforced on title/domain/scope in
    new, and domain/scope in supersede/version, but only config.py's own
    field descriptions ever mentioned this constraint -- an asymmetry
    the codebase's own comments draw the analogy for but never actually
    documented on the live-command side."""
    checks = {
        "new": ("title", "domain", "scope"),
        "supersede": ("domain", "scope"),
        "version": ("domain", "scope"),
        "log": ("summary",),
    }
    for name, fields in checks.items():
        info = COMMANDS[name].describe()
        by_name = {arg["name"]: arg.get("description", "") for arg in info.get("arguments", [])}
        for field in fields:
            assert "field-contains-forbidden-character" in by_name[field], (
                f"{name}'s '{field}' argument never mentions the forbidden-character constraint"
            )


def test_refdate_documents_its_own_actual_lower_bound_rule_per_command():
    """--refdate's
    description was byte-identical across 6 commands even though the
    actual lower-bound rule differs -- new has none at all (a brand new
    decision has no prior history), approve/reject/supersede bound
    against the TARGET's own history, version/revise bound against the
    LATEST family member's history instead (which can be a different
    file than the one named in --file, when branching off an older
    Rejected sibling)."""
    with_lower_bound = ("approve", "reject", "supersede", "version", "revise")
    for name in with_lower_bound:
        refdate_arg = next(arg for arg in COMMANDS[name].describe()["arguments"] if arg["name"] == "refdate")
        for code in ("refdate-invalid-format", "refdate-in-future", "refdate-before-history"):
            assert code in refdate_arg["description"], f"{name}'s refdate description never mentions {code}"

    new_refdate_arg = next(arg for arg in COMMANDS["new"].describe()["arguments"] if arg["name"] == "refdate")
    assert "refdate-invalid-format" in new_refdate_arg["description"]
    assert "refdate-in-future" in new_refdate_arg["description"]
    # new has no lower-bound check at all -- the description must not
    # claim a constraint it doesn't actually enforce.
    assert "refdate-before-history" not in new_refdate_arg["description"]


def test_init_documents_existing_numbers_scan_incomplete_as_not_seed_scoped():
    """Init-existing-numbers-
    scan-incomplete used to be documented only inside the --seed
    argument's own description, in the same breath as codes that really
    are scoped to the already-existing-repository path -- but this one
    fires on a genuinely fresh `init` too (no --seed needed) if a
    decisions folder with an unreadable subdirectory already exists.
    Moved to the top-level description, which every path shares."""
    info = COMMANDS["init"].describe()
    assert "init-existing-numbers-scan-incomplete" in info["description"]


def test_every_family_member_command_documents_family_scan_incomplete():
    """family_members() (used by
    every per-file command's own family guard) now fails closed on an
    unreadable subdirectory instead of merely warning -- documented on
    all 6 commands that call it."""
    for name in _PER_FILE_COMMANDS:
        info = COMMANDS[name].describe()
        text = info["description"] + " ".join(arg.get("description", "") for arg in info.get("arguments", []))
        assert "family-scan-incomplete" in text, f"{name}'s describe() never mentions family-scan-incomplete"


def test_short_flag_aliases_are_documented_in_describe():
    """Every command's real
    parse_flags(aliases=...) accepts a short form (-p, -f, -t, ...), but
    describe() never exposed it anywhere -- an agent relying solely on
    describe()/help (the documented self-description channel for a non-
    interactive caller) had no way to discover these forms exist. The
    schema already tolerates non-standard argument metadata (help.py's
    own "positional" key) -- "alias" follows the same convention."""
    expected = {
        "new": {"path": "-p", "title": "-t", "domain": "-d", "scope": "-s", "refdate": "-r"},
        "approve": {"file": "-f", "refdate": "-r"},
        "reject": {"file": "-f", "refdate": "-r"},
        "undo": {"file": "-f"},
        "supersede": {"file": "-f", "domain": "-d", "scope": "-s", "refdate": "-r"},
        "version": {"file": "-f", "domain": "-d", "scope": "-s", "refdate": "-r", "empty": "-e"},
        "revise": {"file": "-f", "refdate": "-r"},
        "migrate": {"path": "-p"},
        "init": {"path": "-p", "seed": "-s"},
        "explore": {"path": "-p"},
        "log": {"path": "-p", "classification": "-c", "scope": "-s", "refdate": "-r"},
    }
    for name, aliases in expected.items():
        by_name = {arg["name"]: arg for arg in COMMANDS[name].describe()["arguments"]}
        for field, alias in aliases.items():
            assert by_name[field].get("alias") == alias, f"{name}'s '{field}' argument doesn't document '{alias}'"


def test_migrate_documents_its_scan_failed_error_code():
    """Migrate's describe()
    documented migration-scan-unreliable-encoding at length but never
    its structurally identical sibling migration-scan-failed (same scan
    loop, same phase, same all-or-nothing semantics for an OSError
    instead of a lossy decode)."""
    text = COMMANDS["migrate"].describe()["description"]
    assert "migration-scan-failed" in text


def test_every_per_file_command_documents_the_md_auto_suffix():
    """Every
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
    # "warnings" is present
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


def test_version_flag_is_the_one_deliberate_exception_to_json_only_output(capsys):
    """--version/-v is a human-only convenience, never parsed by a script
    or agent -- the one flag allowed to print plain text instead of the
    JSON envelope every other call returns."""
    exit_code = main(["--version"])
    out = capsys.readouterr().out

    assert exit_code == EXIT_SUCCESS
    assert out.startswith("adrpy-ai ")
    assert "Docs:" in out
    assert "Usage: adrpy help" in out
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_short_version_flag_matches_the_long_form(capsys):
    exit_code = main(["-v"])
    out_short = capsys.readouterr().out

    main(["--version"])
    out_long = capsys.readouterr().out

    assert exit_code == EXIT_SUCCESS
    assert out_short == out_long


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
    """Some failures need more than a code and a stderr-only detail
    string to be actionable -- not-latest-version, for
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
    """A real side effect (an encoding
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
    """Distinct from the "no warnings" case below -- warnings=[]
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
    """A malformed invocation must still honor the
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
    """An OSError not translated into a CommandError by the command itself (a
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
