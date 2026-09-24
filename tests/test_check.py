import json

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


def test_an_empty_file_with_an_adr_name_is_no_header_never_an_invalid_header_detail(tmp_path, capsys):
    # A 0-byte file has nothing of this tool's header shape, so check
    # reports it as no-header; adr-file-empty is only ever explore's
    # header.invalid_reason, and check's table must not promise it as an
    # invalid-header detail.
    repo = make_repo(tmp_path, files=[D(1, state="accepted")])
    (repo.folder / "ADR002V01-empty.md").write_bytes(b"")

    code, payload = _run(capsys, ["check", "--path", str(repo.root)])

    assert code == EXIT_FAILURE
    assert [(error["code"], error["detail"]) for error in payload["data"]["errors"]] == [
        (FailureCodes.NO_HEADER, None)
    ]
    entries = {entry["filename"]: entry for entry in explore.run(["--path", str(repo.root)])["decisions"]}
    assert entries["ADR002V01-empty.md"]["header"]["invalid_reason"] == FailureCodes.ADR_FILE_EMPTY
    text = {entry["code"]: entry["condition"] for entry in COMMANDS["check"].describe()["failure_codes"]}
    assert "invalid-header entry starts with" not in text[FailureCodes.ADR_FILE_EMPTY]
    assert "no-header" in text[FailureCodes.ADR_FILE_EMPTY]
