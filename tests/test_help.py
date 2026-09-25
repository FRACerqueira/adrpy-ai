import json
from pathlib import Path

from adrpy.__main__ import main
from adrpy.core.errors import FailureCodes
from adrpy.core.output import EXIT_FAILURE, EXIT_SUCCESS, EXIT_USAGE_ERROR
from adrpy.core.registry import COMMANDS

import pytest


_PER_FILE_COMMANDS = ("approve", "reject", "undo", "supersede", "version", "revise")


def _codes(name):
    return {entry["code"] for entry in COMMANDS[name].describe()["failure_codes"]}


def test_config_and_init_document_folderadr_change_scan_incomplete():
    """folderadr-change-scan-incomplete (the fail-closed path of
    core.lifecycle's folderadr-change guard) is reachable from config and
    init, the only two callers of that guard."""
    for name in ("config", "init"):
        assert "folderadr-change-scan-incomplete" in _codes(name), f"{name}'s failure_codes never lists it"


def test_every_path_based_command_documents_target_directory_not_found():
    """target-directory-not-found (core.lifecycle.resolve_target_and_config,
    raised for every --path-taking command, init included) is in each of
    their failure_codes."""
    for name in ("check", "config", "explore", "init", "log", "migrate", "new"):
        assert "target-directory-not-found" in _codes(name), f"{name}'s failure_codes never lists it"


def test_every_failure_code_is_documented_somewhere():
    """ADR008V01: the actual payoff ADR005V01 named as its own Positive
    Consequence -- a single, grep-able registry makes 'every code is
    documented' a property this test can check mechanically, instead of
    a claim that has to be re-audited by hand every few months. Checks
    the structured `failure_codes` field (not free-form prose
    substring-matching, which the field replaces as this completeness
    check's own source of truth) -- every command's own list, unioned
    across all 14, must cover every FailureCodes attribute."""
    codes = {name: getattr(FailureCodes, name) for name in dir(FailureCodes) if name.isupper()}
    documented = {
        entry["code"] for module in COMMANDS.values() for entry in module.describe().get("failure_codes", [])
    }
    missing = sorted(code for code in codes.values() if code not in documented)
    assert not missing, f"{len(missing)} FailureCodes not in any command's own failure_codes field: {missing}"


def test_every_failure_codes_entry_is_a_real_failure_code():
    """The reverse direction of the completeness check above: a typo'd or
    stale string in some command's own failure_codes field would pass
    the completeness check (it doesn't check for extras) but would be a
    real, silent drift from the registry -- every entry's own `code`
    must be a real FailureCodes value, not just present."""
    real_codes = {getattr(FailureCodes, name) for name in dir(FailureCodes) if name.isupper()}
    for name, module in COMMANDS.items():
        for entry in module.describe().get("failure_codes", []):
            assert entry["code"] in real_codes, f"{name}'s failure_codes has a bogus code: {entry['code']!r}"


def test_no_command_lists_the_same_failure_code_twice():
    """build_failure_codes silently drops a later duplicate in favor of
    the first -- a command accidentally merging two sources that both
    define the same code would not error, just silently keep whichever
    condition text came first. Pins that this doesn't currently happen
    anywhere, so a future merge that DOES introduce one is caught."""
    for name, module in COMMANDS.items():
        codes = [entry["code"] for entry in module.describe().get("failure_codes", [])]
        assert len(codes) == len(set(codes)), f"{name}'s failure_codes has a duplicate entry"


def test_every_failure_codes_entry_has_a_non_empty_condition():
    """A `failure_codes` entry with a blank/missing condition would pass
    every other check here while still being useless to an agent reading
    it -- the whole point of this field is a real one-line explanation,
    not just the bare code string a moment's misconfiguration could
    already recover from the JSON payload's own `code` key."""
    for name, module in COMMANDS.items():
        for entry in module.describe().get("failure_codes", []):
            assert entry.get("condition", "").strip(), f"{name}'s {entry['code']!r} has no condition text"


def test_field_is_blank_is_only_claimed_by_commands_that_can_actually_reach_it():
    """ADR008V01 verification round: field-is-blank was over-claimed by
    approve/reject/undo/revise/migrate -- each of them only ever calls
    reject_embedded_delimiter on a value already `.strip()`-ed upstream
    (header.title/scope/domain via core/header.py's own _extract_cell;
    migrate's own candidate title via an explicit `.strip()` before the
    call), so `value != "" and not value.strip()` can never be true --
    the code is structurally unreachable there. Only supersede/version
    call reject_embedded_delimiter on a RAW, unstripped --scope/--domain
    flag value (falling back to the pre-stripped header value only when
    the flag is omitted), so they're the only two that can genuinely
    raise it."""
    for name in ("approve", "reject", "undo", "revise", "migrate"):
        codes = {entry["code"] for entry in COMMANDS[name].describe()["failure_codes"]}
        assert "field-is-blank" not in codes, f"{name} claims field-is-blank but can never reach it"
    for name in ("supersede", "version"):
        codes = {entry["code"] for entry in COMMANDS[name].describe()["failure_codes"]}
        assert "field-is-blank" in codes, f"{name} can genuinely raise field-is-blank via a raw --scope/--domain flag"


def test_installconfig_documents_io_error():
    """ADR008V01 verification round: installconfig.py's own 3
    atomic_write_text call sites are never wrapped in attach_warnings (or
    any other OSError-catching mechanism, unlike every other write
    command) -- a raw OSError (e.g. a PermissionError exhausting
    atomic_write_bytes' own retry budget) propagates uncaught to
    __main__'s generic handler, which reports it as io-error, the exact
    same way every other writer's own io-error claim is already
    justified."""
    codes = {entry["code"] for entry in COMMANDS["installconfig"].describe()["failure_codes"]}
    assert "io-error" in codes


def test_every_path_based_command_except_init_documents_config_not_found():
    """config-not-found (resolve_target_and_config with require_config=True:
    every --path-taking command except init, which decides for itself
    whether a missing config is an error)."""
    for name in ("check", "config", "explore", "log", "migrate", "new"):
        assert "config-not-found" in _codes(name), f"{name}'s failure_codes never lists it"


def test_every_per_file_command_documents_file_not_found_and_cannot_determine_root_path():
    """file-not-found/cannot-determine-root-path (resolving --file, the
    sibling of resolve_target_and_config above) on every command that takes
    --file instead of --path."""
    for name in _PER_FILE_COMMANDS:
        codes = _codes(name)
        assert "file-not-found" in codes, f"{name}'s failure_codes never lists file-not-found"
        assert "cannot-determine-root-path" in codes, f"{name}'s failure_codes never lists cannot-determine-root-path"


def test_init_documents_config_already_exists_and_config_file_not_found():
    """config-already-exists (a bare init on an existing repository) and
    config-file-not-found (a bad --seed path)."""
    codes = _codes("init")
    assert "config-already-exists" in codes
    assert "config-file-not-found" in codes


def test_init_documents_the_three_length_too_small_codes():
    """lenseq/lenversion/lenrevision-too-small-for-existing-decisions
    (init.py, once the existing-numbers scan itself succeeds)."""
    codes = _codes("init")
    assert "lenseq-too-small-for-existing-decisions" in codes
    assert "lenversion-too-small-for-existing-decisions" in codes
    assert "lenrevision-too-small-for-existing-decisions" in codes


def test_config_documents_field_not_an_integer_and_field_not_a_boolean():
    """field-not-an-integer (lenseq/lenversion/lenrevision) and
    field-not-a-boolean (disableplugins)."""
    codes = _codes("config")
    assert "field-not-an-integer" in codes
    assert "field-not-a-boolean" in codes


def test_new_supersede_and_version_document_the_forbidden_character_constraint():
    """reject_embedded_delimiter (core/security.py) is enforced on the
    free-text flags of new (title/domain/scope), supersede/version
    (domain/scope) and log (summary)."""
    for name in ("new", "supersede", "version", "log"):
        assert "field-contains-forbidden-character" in _codes(name), f"{name}'s failure_codes never lists it"


def test_refdate_documents_its_own_actual_lower_bound_rule_per_command():
    """Every command taking --refdate lists its format and future-date
    codes; only the ones that bound it by an earlier date of the target
    (approve/reject by its creation date, supersede/version/revise by its
    Changed or creation date) list refdate-before-history -- new has no
    lower bound at all (a brand new decision has no prior history)."""
    for name in ("approve", "reject", "supersede", "version", "revise"):
        codes = _codes(name)
        for code in ("refdate-invalid-format", "refdate-in-future", "refdate-before-history"):
            assert code in codes, f"{name}'s failure_codes never lists {code}"

    codes = _codes("new")
    assert "refdate-invalid-format" in codes
    assert "refdate-in-future" in codes
    # new must not claim a constraint it doesn't enforce.
    assert "refdate-before-history" not in codes


def test_init_documents_existing_numbers_scan_incomplete():
    """init-existing-numbers-scan-incomplete fires on a fresh init too (no
    --seed needed) when a decisions folder with an unreadable subdirectory
    already exists."""
    assert "init-existing-numbers-scan-incomplete" in _codes("init")


def test_every_file_command_documents_the_repository_validation():
    """Every one of the 6 per-file commands validates the whole
    repository before any other rule (repository-inconsistent) and
    refuses a target outside the decisions folder
    (target-outside-folderadr)."""
    for name in _PER_FILE_COMMANDS:
        codes = _codes(name)
        for code in ("repository-inconsistent", "target-outside-folderadr"):
            assert code in codes, f"{name}'s failure_codes never lists {code}"


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
    """migration-scan-failed: a scanned file whose header cannot be read
    refuses the whole run."""
    assert "migration-scan-failed" in _codes("migrate")


def test_every_per_file_command_documents_the_md_auto_suffix():
    """Every
    per-file command's `--file` silently gets '.md' appended when the
    given path has no extension (load_target's own doing) --
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


def test_every_registered_command_has_a_non_empty_summary():
    """Structural, not a hardcoded list of names -- a future command
    added to COMMANDS without its own `summary` would otherwise show up
    blank in the bare `adrpy help` listing with nothing catching it."""
    for name, command in COMMANDS.items():
        summary = command.describe().get("summary")
        assert summary, f"{name} has no summary"


def test_bare_help_is_summarized_by_default(capsys):
    exit_code = main(["help"])
    payload = json.loads(capsys.readouterr().out)["data"]

    assert exit_code == EXIT_SUCCESS
    assert len(payload["commands"]) == len(COMMANDS)
    for entry in payload["commands"]:
        assert set(entry.keys()) == {"name", "summary"}
    assert "arguments" not in payload["commands"][0]
    assert "description" not in payload["commands"][0]
    assert "hint" in payload
    assert "defaults" in payload


def test_bare_help_defaults_reflects_the_built_in_default_with_no_install_level_config(capsys):
    """The autouse fixture forces no install-level config on this
    machine for every test -- this is the baseline `source` value."""
    exit_code = main(["help"])
    payload = json.loads(capsys.readouterr().out)["data"]

    assert exit_code == EXIT_SUCCESS
    assert payload["defaults"]["source"] == "built-in"
    assert payload["defaults"]["folderadr"] == "doc/adr"
    assert payload["defaults"]["prefix"] == "ADR"
    assert "headertitlefile" not in payload["defaults"]


def test_bare_help_defaults_reflects_an_install_level_config_when_one_exists(capsys, monkeypatch):
    from adrpy.core import install_config

    install_text = (Path("tests") / "fixtures" / "adr-config.adrplus").read_text(encoding="utf-8")
    monkeypatch.setattr(install_config, "read_install_config_text", lambda *args, **kwargs: install_text)

    exit_code = main(["help"])
    payload = json.loads(capsys.readouterr().out)["data"]

    assert exit_code == EXIT_SUCCESS
    assert payload["defaults"]["source"] == "install-config"


def test_help_full_returns_every_commands_complete_contract(capsys):
    exit_code = main(["help", "--full"])
    payload = json.loads(capsys.readouterr().out)["data"]

    assert exit_code == EXIT_SUCCESS
    assert payload["commands"] == [command.describe() for command in COMMANDS.values()]
    assert "defaults" not in payload
    assert "hint" not in payload


def test_help_full_is_ignored_when_a_specific_command_is_named(capsys):
    exit_code = main(["help", "init", "--full"])
    payload = json.loads(capsys.readouterr().out)["data"]

    assert exit_code == EXIT_SUCCESS
    assert payload["commands"] == [COMMANDS["init"].describe()]


def test_help_rejects_an_unknown_flag(capsys):
    exit_code = main(["help", "--bogus"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_USAGE_ERROR
    assert payload["success"] is False


def test_help_rejects_more_than_one_command_name(capsys):
    exit_code = main(["help", "init", "new"])
    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_USAGE_ERROR
    assert payload["success"] is False


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
    # Compared against the live describe() output, not a hand-copied
    # literal -- the whole point of this command is that its own contract
    # is the single source of truth; hardcoding a copy here would just
    # recreate the drift risk this project's own describe()-driven docs
    # exist to avoid.
    assert payload["data"]["commands"] == [COMMANDS["help"].describe()]


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
    repair, an orphan-temp-file cleanup, a retried
    write) that already happened before a command goes on to fail for an
    unrelated reason must not be silently dropped -- the failure envelope
    must carry a trace that it already occurred."""
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
    parse_flags (missing required argument, unknown flag) must not print
    free text to stderr with nothing at all on stdout."""
    exit_code = main(["new", "--path", "."])  # missing required --title

    payload = json.loads(capsys.readouterr().out)

    assert exit_code == EXIT_USAGE_ERROR
    assert payload["success"] is False
    assert payload["code"] == "usage-error"


def test_unhandled_oserror_still_emits_json_on_stdout(capsys, monkeypatch, tmp_path):
    """An OSError not translated into a CommandError by the command itself (a
    real repro: adrpy.exe new against a path that resolves through an
    NTFS Alternate Data Stream) must not propagate as a raw traceback
    with EMPTY stdout -- that would break the one contract this whole
    project exists to provide."""
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


def test_keyboard_interrupt_still_emits_json_on_stdout(capsys, monkeypatch):
    """Round 36 core resilience front: KeyboardInterrupt is a
    BaseException, not an Exception -- the generic except Exception clause
    above never sees it, so before this fix it propagated raw, with empty
    stdout, the exact failure mode this project's own JSON-contract
    guarantee exists to prevent."""
    from adrpy.cli import help as help_command

    def boom(_args):
        raise KeyboardInterrupt()

    monkeypatch.setattr(help_command, "run", boom)

    exit_code = main(["help"])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == EXIT_FAILURE
    assert payload["success"] is False
    assert payload["code"] == "interrupted"


def test_an_adrpy_failure_carries_its_detail_on_stdout_and_the_same_text_on_stderr(tmp_path, capsys):
    # ADR010V01, on adrpy's own entry point.
    from adrpy.__main__ import main as adrpy_main

    adrpy_main(["frobnicate"])
    captured = capsys.readouterr()
    out = json.loads(captured.out)

    assert out["code"] == "unknown-command"
    assert "frobnicate" in out["detail"]
    assert captured.err.strip() == out["detail"]


def _main_json(capsys, argv):
    capsys.readouterr()
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


@pytest.mark.parametrize("flag", ["--help", "-h"])
@pytest.mark.parametrize("command", ["check", "new", "log", "help"])
def test_a_command_followed_by_help_describes_that_command(capsys, command, flag):
    expected = _main_json(capsys, ["help", command])

    assert _main_json(capsys, [command, flag]) == expected
    if command != "help":
        assert _main_json(capsys, [command, "--path", ".", flag]) == expected


def test_help_answers_any_dash_token_as_an_unknown_argument(capsys):
    code, response = _main_json(capsys, ["help", "-x"])

    assert code == EXIT_USAGE_ERROR
    assert response == {"success": False, "code": "usage-error", "detail": "Unknown argument: -x"}


def test_a_missing_required_flag_shows_an_example_and_where_to_read_more(capsys):
    code, response = _main_json(capsys, ["check"])

    assert code == EXIT_USAGE_ERROR
    assert response["code"] == "usage-error"
    assert "e.g. `adrpy check --path .`" in response["detail"]
    assert "see `adrpy help check`" in response["detail"]
