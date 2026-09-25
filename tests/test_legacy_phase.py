"""The phase rule for legacy-scheme names (recognized only through
migrationpattern): once any file in folderadr has a valid header migrate
did not write (migrate no longer runs), a legacy-scheme name without a
header is not a decision anywhere; before that it is a no-header decision,
as migrate expects."""

import json

import pytest

from adrpy.__main__ import main
from adrpy.cli import config, explore, init, migrate, new
from adrpy.core.consistency import check_repository
from adrpy.core.errors import CommandError, FailureCodes, UsageError
from adrpy.core.output import EXIT_FAILURE, EXIT_SUCCESS

from conftest import D, make_repo

_PATTERN = {"migrationpattern": "N00:04T05"}


def _run(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def _note(repo, name="0099-notes.md", content="# a dated note, not a decision\n"):
    path = repo.folder / name
    path.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return path


def _phase_warnings(warnings):
    return [warning for warning in warnings if "match migrationpattern but have no header" in warning]


# ------------------------------------------------------------ pre-adoption --


def test_before_adoption_a_legacy_name_without_header_is_still_a_no_header_decision(tmp_path, capsys):
    repo = make_repo(tmp_path, config=_PATTERN)
    _note(repo, "0001-use-postgres.md")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert [error["code"] for error in payload["data"]["errors"]] == [FailureCodes.NO_HEADER]
    assert "warnings" not in payload


def test_a_header_shaped_but_invalid_legacy_file_does_not_adopt_the_repository(tmp_path):
    repo = make_repo(tmp_path, config=_PATTERN)
    _note(repo, "0001-damaged.md", "|--|--|\n# damaged\n")
    _note(repo, "0002-plain.md")

    _snapshot, errors = check_repository(repo.folder, repo.config)

    assert sorted(error["code"] for error in errors) == [FailureCodes.INVALID_HEADER, FailureCodes.NO_HEADER]


# ----------------------------------------------------------------- adopted --


def test_after_adoption_a_legacy_name_without_header_is_ignored_and_warned_about(tmp_path, capsys):
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1)])
    _note(repo)

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_SUCCESS
    assert payload["data"]["decisions"] == 1
    [warning] = payload["data"]["warnings"]
    assert warning.startswith(
        "1 file(s) match migrationpattern but have no header, so they are not decisions: 0099-notes.md."
    )
    assert "migrate does not run" in warning and "header by hand" in warning
    assert "move them out of the decisions folder" in warning
    explored = explore.run(["--path", str(repo.root)])
    assert warning in explored["warnings"]
    assert explored["consistency"]["errors"] == []
    [entry] = [entry for entry in explored["decisions"] if entry["filename"] == "0099-notes.md"]
    assert (entry["scheme"], entry["number"], entry["header"]["state"]) == (None, 0, "no-header")


def test_migrated_decisions_alone_do_not_end_the_adoption(tmp_path, capsys):
    # migrate can still run, so a legacy name without a header is still
    # one of its decisions (no-header) and blocks until migrate finishes.
    repo = make_repo(
        tmp_path,
        config=_PATTERN,
        files=[D(1, version=0, migrated=True, state="placeholder", filename="0001-first.md")],
    )
    _note(repo)

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert [error["code"] for error in payload["data"]["errors"]] == [FailureCodes.NO_HEADER]


def test_the_phase_warning_also_comes_with_a_failing_check(tmp_path, capsys):
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1), D(1, title="Other")])
    _note(repo)

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert sorted(error["code"] for error in payload["data"]["errors"]) == [
        FailureCodes.DUPLICATE_NUMBER,
        FailureCodes.PENDING_DUPLICATE,
    ]
    assert len(_phase_warnings(payload["warnings"])) == 1


def test_a_file_is_named_by_one_warning_only(tmp_path, capsys):
    # 0099-notes.md starts with a digit, but migrationpattern recognizes
    # it: it is the phase warning's, never also the unrecognized one's.
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1)])
    _note(repo)
    _note(repo, "12-x.md")

    _code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    mentioning = [warning for warning in payload["data"]["warnings"] if "0099-notes.md" in warning]
    assert len(mentioning) == 1 and _phase_warnings(mentioning)
    assert len(payload["data"]["warnings"]) == 2


def test_after_adoption_a_zero_byte_legacy_file_is_ignored_too(tmp_path, capsys):
    # The tool only ever creates current-scheme names, so a 0-byte file
    # with a legacy-only name is never an interrupted create's reservation.
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1)])
    _note(repo, "0099-empty.md", b"")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_SUCCESS
    assert len(_phase_warnings(payload["data"]["warnings"])) == 1


def test_new_after_adoption_does_not_count_the_ignored_file_for_the_next_number(tmp_path):
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1)])
    _note(repo)

    result = new.run(["--path", str(repo.root), "--title", "Next"])

    assert result["created"].endswith("ADR002V01-next.md")
    assert _phase_warnings(explore.run(["--path", str(repo.root)])["warnings"])


def test_writing_commands_warn_that_an_ignored_file_may_share_a_number(tmp_path):
    # new may give a decision the number an ignored file carries: said at
    # once, with what to do, before a hand-written header collides with it.
    from adrpy.cli import approve

    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1, state="proposed")])
    _note(repo, "0002-legacy.md")

    created = new.run(["--path", str(repo.root), "--title", "Next"])
    approved = approve.run(["--file", str(repo.folder / "ADR001V01-decision-1.md")])

    for result in (created, approved):
        [warning] = _phase_warnings(result["warnings"])
        assert "0002-legacy.md" in warning
        assert "number" in warning and "rename" in warning


@pytest.mark.parametrize("command", ["approve", "reject", "undo", "version", "supersede"])
def test_a_command_on_an_ignored_file_is_refused_as_not_a_decision_before_validation(tmp_path, command):
    from adrpy.core.registry import COMMANDS

    # The repository is otherwise inconsistent: the target's own name is
    # still refused first, as for any file that is not a decision.
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1), D(1, title="Other")])
    note = _note(repo)

    with pytest.raises(CommandError) as excinfo:
        COMMANDS[command].run(["--file", str(note)])

    assert excinfo.value.code == FailureCodes.FILENAME_NOT_RECOGNIZED


def test_a_legacy_file_with_a_hand_copied_header_is_a_decision_in_both_phases(tmp_path, capsys):
    alone = make_repo(tmp_path / "alone", config=_PATTERN, files=[D(1, version=0, filename="0001-copied.md")])
    with_tool = make_repo(
        tmp_path / "with", config=_PATTERN, files=[D(2), D(1, version=0, filename="0001-copied.md")]
    )

    for repo, count in ((alone, 1), (with_tool, 2)):
        code, payload = _run(capsys, ["check", "--path", str(repo.root)])
        assert (code, payload["data"]["decisions"], payload["data"]["warnings"]) == (EXIT_SUCCESS, count, [])


def test_an_invalid_header_legacy_file_is_still_an_error_after_adoption(tmp_path):
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1)])
    _note(repo, "0099-damaged.md", "|--|--|\n# damaged\n")

    _snapshot, errors = check_repository(repo.folder, repo.config)

    assert [error["code"] for error in errors] == [FailureCodes.INVALID_HEADER]


def test_after_a_partial_migrate_the_leftovers_still_block_new_so_migrate_can_finish(tmp_path):
    # Migrated headers alone do not end the adoption: while migrate can
    # still run, a `new` would create a decision it did not write and lock
    # the leftovers out of migrate for good.
    repo = make_repo(
        tmp_path,
        config=_PATTERN,
        files=[D(1, version=0, migrated=True, state="placeholder", filename="0001-first.md")],
    )
    _note(repo, "0002-second.md", "# second\n")

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(repo.root), "--title", "Fresh"])

    assert excinfo.value.code == FailureCodes.REPOSITORY_INCONSISTENT
    assert migrate.run(["--path", str(repo.root)])["migrated"] == [str(repo.folder / "0002-second.md")]


def test_a_rerun_after_a_partial_migrate_migrates_the_leftovers(tmp_path, capsys):
    repo = make_repo(
        tmp_path,
        config=_PATTERN,
        files=[D(1, version=0, migrated=True, state="placeholder", filename="0001-first.md")],
    )
    _note(repo, "0002-second.md", "# second\n")

    before_code, before = _run(capsys, ["check", "--path", str(repo.root)])
    result = migrate.run(["--path", str(repo.root)])
    code, after = _run(capsys, ["check", "--path", str(repo.root)])

    assert before_code == EXIT_FAILURE
    assert [error["code"] for error in before["data"]["errors"]] == [FailureCodes.NO_HEADER]
    assert result["migrated"] == [str(repo.folder / "0002-second.md")]
    assert (code, after["data"]["decisions"], after["data"]["warnings"]) == (EXIT_SUCCESS, 2, [])


def test_the_migrationpattern_guard_is_unchanged(tmp_path):
    # Hand-written files it only matches by name never block a change;
    # a migrated legacy decision does.
    unmigrated = make_repo(tmp_path / "a", config=_PATTERN, files=[D(1)])
    _note(unmigrated)
    config.run(["--path", str(unmigrated.root), "--migrationpattern", "N00:04T04"])

    migrated = make_repo(
        tmp_path / "b", config=_PATTERN, files=[D(1, version=0, migrated=True, state="placeholder", filename="0001-a.md")]
    )
    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(migrated.root), "--migrationpattern", "N00:04T04"])
    assert excinfo.value.code == FailureCodes.STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS


def test_the_blanket_guard_does_not_count_an_ignored_file_as_an_existing_decision(tmp_path):
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1)])
    _note(repo)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(repo.root), "--separator", "_"])

    assert excinfo.value.code == FailureCodes.STATUS_OR_SEPARATOR_CHANGE_BLOCKED_BY_EXISTING_DECISIONS
    assert excinfo.value.data["existing_decisions"] == 1


def test_init_seed_does_not_count_an_ignored_file_among_the_existing_numbers(tmp_path):
    repo = make_repo(tmp_path, config=_PATTERN, files=[D(1)])
    _note(repo, "12345-notes.md")
    seed = json.loads(init.default_repo_config_text())
    seed.update(folderadr="doc/adr", prefix="ADR", lenseq=3, migrationpattern="N00:05T06")
    seed_path = tmp_path / "seed.json"
    seed_path.write_text(json.dumps(seed), encoding="utf-8")

    init.run(["--path", str(repo.root), "--seed", str(seed_path)])


# --------------------------------------------- explore --migrationpattern --


def _tree(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


def test_explore_previews_a_migrationpattern_like_config_without_writing(tmp_path):
    repo = make_repo(tmp_path)
    _note(repo, "0001-a.md")
    _note(repo, "0002-b.md")
    before = _tree(repo.root)

    explored = explore.run(["--path", str(repo.root), "--migrationpattern", "N00:04T04"])

    assert _tree(repo.root) == before
    configured = config.run(["--path", str(repo.root), "--migrationpattern", "N00:04T04"])
    assert explored["migrationpattern_preview"] == configured["migrationpattern_preview"]
    assert [entry["title"] for entry in explored["migrationpattern_preview"]] == ["-a", "-b"]
    misread = [warning for warning in configured["warnings"] if "start with a separator" in warning]
    assert misread and set(misread) <= set(explored["warnings"])


def test_explore_without_the_flag_has_no_preview(tmp_path):
    repo = make_repo(tmp_path)

    assert "migrationpattern_preview" not in explore.run(["--path", str(repo.root)])


def test_explore_preview_of_a_missing_folder_is_empty_and_creates_nothing(tmp_path):
    repo = make_repo(tmp_path)
    repo.folder.rmdir()

    explored = explore.run(["--path", str(repo.root), "--migrationpattern", "N00:04T05"])

    assert explored["migrationpattern_preview"] == []
    assert not repo.folder.exists()


def test_explore_refuses_an_invalid_or_empty_preview_pattern(tmp_path):
    repo = make_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        explore.run(["--path", str(repo.root), "--migrationpattern", "bogus"])
    assert excinfo.value.code == FailureCodes.CONFIG_MIGRATIONPATTERN_INVALID
    with pytest.raises(UsageError):
        explore.run(["--path", str(repo.root), "--migrationpattern", ""])
