import json
import os
import sys

import pytest

from adrpy.__main__ import main
from adrpy.cli import explore
from adrpy.core.errors import FailureCodes
from adrpy.core.output import EXIT_FAILURE, EXIT_SUCCESS
from adrpy.core.registry import COMMANDS

from conftest import D, make_repo


def _run(capsys, argv):
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_check_succeeds_on_a_consistent_repository(tmp_path, capsys):
    repo = make_repo(tmp_path, files=[D(1, state="superseded", successor=2), D(2, suffix=1), D(3)])

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_SUCCESS
    assert payload == {"success": True, "data": {"decisions": 3, "warnings": []}}


def test_check_fails_with_every_error_listed(tmp_path, capsys):
    repo = make_repo(tmp_path, files=[D(1, title="One"), D(1, title="Two", state="accepted"), D(2, created="Accepted", changed=None)])

    code, payload = _run(capsys, ["check", "-p", str(repo.root)])

    assert code == EXIT_FAILURE
    assert payload["success"] is False
    assert payload["code"] == FailureCodes.REPOSITORY_INCONSISTENT
    codes = sorted(error["code"] for error in payload["data"]["errors"])
    assert codes == [FailureCodes.DUPLICATE_NUMBER, FailureCodes.INVALID_STATUS_COMBINATION]


def test_check_reports_a_missing_repository_like_the_other_path_commands(tmp_path, capsys):
    code, payload = _run(capsys, ["check", "--path", str(tmp_path / "missing")])

    assert code == EXIT_FAILURE
    assert payload["code"] == FailureCodes.TARGET_DIRECTORY_NOT_FOUND


def test_check_is_registered_and_documents_its_failure_codes():
    info = COMMANDS["check"].describe()
    codes = {entry["code"] for entry in info["failure_codes"]}

    assert info["name"] == "check"
    assert FailureCodes.REPOSITORY_INCONSISTENT in codes
    assert FailureCodes.DUPLICATE_NUMBER in codes and FailureCodes.SCAN_INCOMPLETE in codes


def test_explore_reports_consistency_errors_and_still_succeeds(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, state="accepted"), D(2, suffix=1)])

    payload = explore.run(["--path", str(repo.root)])

    assert len(payload["decisions"]) == 2
    assert [error["code"] for error in payload["consistency"]["errors"]] == [
        FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR
    ]


def test_explore_reports_no_consistency_errors_on_a_consistent_repository(tmp_path):
    repo = make_repo(tmp_path, files=[D(1)])

    assert explore.run(["--path", str(repo.root)])["consistency"] == {"errors": []}


@pytest.mark.parametrize("folder_exists", [True, False])
def test_explore_consistency_is_empty_without_decisions(tmp_path, folder_exists):
    repo = make_repo(tmp_path)
    if not folder_exists:
        repo.folder.rmdir()

    assert explore.run(["--path", str(repo.root)])["consistency"] == {"errors": []}


def test_a_file_holding_only_a_bom_is_no_header_without_the_0_byte_detail(tmp_path, capsys):
    # Not what an interrupted create leaves (that is 0 bytes): an editor's
    # empty UTF-8 file.
    repo = make_repo(tmp_path, files=[D(1, state="accepted")])
    (repo.folder / "ADR002V01-bom.md").write_bytes(b"\xef\xbb\xbf")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert [(error["code"], error["detail"]) for error in payload["data"]["errors"]] == [
        (FailureCodes.NO_HEADER, None)
    ]


def test_an_empty_file_with_an_adr_name_is_no_header_never_an_invalid_header_detail(tmp_path, capsys):
    # A 0-byte file has nothing of this tool's header shape, so check
    # reports it as no-header; adr-file-empty is only ever explore's
    # header.invalid_reason, and check's table must not promise it as an
    # invalid-header detail. Its detail says it is empty (a create
    # interrupted after reserving the name leaves exactly this).
    repo = make_repo(tmp_path, files=[D(1, state="accepted")])
    (repo.folder / "ADR002V01-empty.md").write_bytes(b"")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert [(error["code"], error["detail"]) for error in payload["data"]["errors"]] == [
        (FailureCodes.NO_HEADER, "0-byte file (most likely left by an interrupted create).")
    ]
    entries = {entry["filename"]: entry for entry in explore.run(["--path", str(repo.root)])["decisions"]}
    assert entries["ADR002V01-empty.md"]["header"]["invalid_reason"] == FailureCodes.ADR_FILE_EMPTY
    text = {entry["code"]: entry["condition"] for entry in COMMANDS["check"].describe()["failure_codes"]}
    assert "invalid-header entry starts with" not in text[FailureCodes.ADR_FILE_EMPTY]
    assert "no-header" in text[FailureCodes.ADR_FILE_EMPTY]


def test_every_command_that_loads_an_empty_config_says_it_is_empty(tmp_path, capsys):
    (tmp_path / "adr-config.adrplus").write_bytes(b"")
    (tmp_path / "doc" / "adr").mkdir(parents=True)
    (tmp_path / "doc" / "adr" / "ADR001V01-x.md").write_text("# x\n", encoding="utf-8")

    log_args = ["--classification", "scope-note", "--scope", "x", "--slug", "x", "--summary", "x", "--body", "x"]
    for argv in (
        ["check", "--path", str(tmp_path)],
        ["explore", "--path", str(tmp_path)],
        ["config", "--path", str(tmp_path)],
        ["new", "--path", str(tmp_path), "--title", "x"],
        ["migrate", "--path", str(tmp_path)],
        ["log", "--path", str(tmp_path), *log_args],
        ["approve", "--file", str(tmp_path / "doc" / "adr" / "ADR001V01-x.md")],
    ):
        _code, response = _run(capsys, argv)
        assert response["code"] == "config-file-empty", argv
        assert "interrupted init" in response["detail"]


@pytest.mark.parametrize("tool_created", [False, True])
def test_check_and_explore_warn_about_md_files_that_look_like_decisions_but_are_not_recognized(
    tmp_path, capsys, tool_created
):
    # Decisions written before adrpy (e.g. 0001-use-x.md) are invisible to
    # every rule until migrationpattern names them: say so, without
    # failing, and without noise for README/INDEX. Where the tool already
    # created a decision, migrate refuses: the warning says what works.
    repo = make_repo(tmp_path, files=[D(1)] if tool_created else [D(1, state="placeholder", migrated=True)])
    for name in ("0001-use-postgres.md", "0002-use-rest.md", "README.md", "INDEX.md", "notes.md"):
        (repo.folder / name).write_text("# x\n", encoding="utf-8")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_SUCCESS
    assert payload["data"]["decisions"] == 1
    [warning] = payload["data"]["warnings"]
    assert warning.startswith("2 .md file(s) in doc/adr are not recognized: 0001-use-postgres.md, 0002-use-rest.md.")
    assert "README.md" not in warning
    if tool_created:
        assert "migrate does not run" in warning and "header by hand" in warning
    else:
        assert "set migrationpattern" in warning and "`adrpy migrate`" in warning and "explore" in warning
    assert warning in explore.run(["--path", str(repo.root)])["warnings"]


def test_the_unrecognized_file_warning_also_comes_with_a_failing_check(tmp_path, capsys):
    repo = make_repo(tmp_path, files=[D(1), D(1, title="Other")])
    (repo.folder / "0001-use-postgres.md").write_text("# x\n", encoding="utf-8")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert payload["code"] == FailureCodes.REPOSITORY_INCONSISTENT
    assert [w.split(":")[0] for w in payload["warnings"]] == ["1 .md file(s) in doc/adr are not recognized"]


def test_a_failing_check_without_that_warning_has_no_warnings_key(tmp_path, capsys):
    repo = make_repo(tmp_path, files=[D(1), D(1, title="Other")])

    _code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert "warnings" not in payload


def test_in_a_tool_created_repository_naming_the_files_without_a_header_keeps_them_out_as_the_warning_says(
    tmp_path, capsys
):
    # The warning's claim, checked: once migrationpattern names them,
    # they are still not decisions without a header (the phase rule), so
    # commands go on and the other warning names them.
    from adrpy.cli import config, new

    repo = make_repo(tmp_path, files=[D(1)])
    (repo.folder / "0001-use-postgres.md").write_text("# x\n", encoding="utf-8")

    config.run(["--path", str(repo.root), "--migrationpattern", "N00:04T05"])
    code, _payload = _run(capsys, ["new", "--path", str(repo.root), "--title", "Next"])
    _code, checked = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_SUCCESS
    assert checked["data"]["decisions"] == 2
    [warning] = checked["data"]["warnings"]
    assert warning.startswith("1 file(s) match migrationpattern but have no header, so they are not decisions")


def test_no_unrecognized_file_warning_without_decision_like_names(tmp_path, capsys):
    repo = make_repo(tmp_path, files=[D(1)])
    (repo.folder / "README.md").write_text("# x\n", encoding="utf-8")

    _code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert payload["data"]["warnings"] == []


# ------------------------------------------------------------- folderlog --

_ENTRY = "2026-09-18--scope-note--lock--a-note.md"


def _log_dir(repo):
    folder = repo.root / "doc" / "decision-log"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / _ENTRY).write_text("# A note\n\nBody.\n", encoding="utf-8")
    (folder / "INDEX.md").write_text("# Decision log index\n", encoding="utf-8")
    (folder / "CYCLES.md").write_text("# Cycles\n", encoding="utf-8")
    return folder


def _log_warnings(warnings):
    return [warning for warning in warnings if "are not decision-log entries" in warning]


def test_check_and_explore_warn_about_a_file_in_folderlog_that_is_not_an_entry(tmp_path, capsys):
    # An agent moved a meeting note INTO the decision log: `log` then
    # refuses to write; check says so first, without failing.
    from adrpy.cli import log
    from adrpy.core.errors import CommandError

    repo = make_repo(tmp_path, files=[D(1)])
    folder = _log_dir(repo)
    (folder / "meeting-notes.md").write_text("# Team meeting\n", encoding="utf-8")
    (folder / "sub").mkdir()
    (folder / "sub" / "2026-09-18--not-a-class--lock--x.md").write_text("# x\n", encoding="utf-8")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_SUCCESS
    [warning] = payload["data"]["warnings"]
    assert warning.startswith(
        "2 file(s) in doc/decision-log are not decision-log entries: meeting-notes.md, "
        "sub/2026-09-18--not-a-class--lock--x.md."
    )
    # The file is the user's: an agent must ask, never move it to get past
    # the refusal (a real run moved it silently and wrote the entry).
    assert "the user's" in warning and "ask where they belong" in warning and "never delete" in warning
    assert "Move them out" not in warning and "`adrpy log` refuses" in warning
    assert "INDEX.md" not in warning and "CYCLES.md" not in warning and _ENTRY not in warning
    assert warning in explore.run(["--path", str(repo.root)])["warnings"]
    # The same recognition `log` refuses on.
    with pytest.raises(CommandError) as excinfo:
        log.run(
            ["--path", str(repo.root), "--classification", "scope-note", "--scope", "lock", "--slug", "b",
             "--summary", "B", "--body", "B.", "--refdate", "2026-09-18"]
        )
    assert excinfo.value.code == FailureCodes.LOG_DIRECTORY_CONTAINS_UNRECOGNIZED_FILE
    assert "the user's file" in excinfo.value.detail and "ask where it belongs" in excinfo.value.detail


def test_no_folderlog_warning_for_a_clean_log_or_a_missing_one(tmp_path, capsys):
    clean = make_repo(tmp_path / "clean", files=[D(1)])
    _log_dir(clean)
    missing = make_repo(tmp_path / "missing", files=[D(1)])

    for repo in (clean, missing):
        code, payload = _run(capsys, ["check", "--path", str(repo.root)])
        assert (code, payload["data"]["warnings"]) == (EXIT_SUCCESS, [])
        assert _log_warnings(explore.run(["--path", str(repo.root)])["warnings"]) == []
    assert not (missing.root / "doc" / "decision-log").exists()


def test_the_folderlog_warning_also_comes_with_a_failing_check(tmp_path, capsys):
    repo = make_repo(tmp_path, files=[D(1), D(1, title="Other")])
    (_log_dir(repo) / "notes.md").write_text("# x\n", encoding="utf-8")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert len(_log_warnings(payload["warnings"])) == 1


def test_check_warns_about_a_decision_name_too_long_to_rewrite(tmp_path):
    from adrpy.cli import check, init, new

    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Short", "--refdate", "2026-01-01"])
    short = tmp_path / "doc" / "adr" / "ADR001V01-short.md"
    long = short.with_name(f"ADR001V01-{'b' * 227}.md")
    short.rename(long)

    result = check.run(["--path", str(tmp_path)])

    assert result["decisions"] == 1
    assert any(long.name in warning and "234" in warning for warning in result["warnings"])


@pytest.mark.skipif(sys.platform != "win32", reason="NTFS accepts an unpaired surrogate in a name; POSIX gets one from an undecodable byte")
def test_check_reads_a_decision_whose_name_holds_an_unpaired_surrogate(tmp_path):
    from adrpy.cli import check, init, new

    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Alpha one", "--refdate", "2026-01-01"])
    adr = tmp_path / "doc" / "adr"
    os.rename(adr / "ADR001V01-alpha-one.md", adr / "ADR001V01-alpha-\ud800.md")

    assert check.run(["--path", str(tmp_path)])["decisions"] == 1
