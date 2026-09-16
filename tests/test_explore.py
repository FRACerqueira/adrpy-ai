import json
import subprocess
import sys
from datetime import date

from adrpy.cli import explore
from adrpy.core.config import parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header

import pytest

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _default_config_dict():
    with open(FIXTURE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _write_repo(tmp_path, config_dict, decisions):
    config_text = json.dumps(config_dict)
    (tmp_path / "adr-config.adrplus").write_text(config_text, encoding="utf-8")
    config = parse_repo_config(config_text)

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True, exist_ok=True)
    for filename, content in decisions.items():
        # newline="": content already carries build_header's real line
        # endings (os.linesep) -- the default write-mode translation would
        # double every "\r" into "\r\r\n", corrupting the fixed 12-line
        # header that parse_header expects.
        with open(adr_dir / filename, "w", encoding="utf-8", newline="") as handle:
            handle.write(content)
    return config


def _decision_text(config, **record_kwargs):
    record = DecisionRecord(**record_kwargs)
    return build_header(config, record) + "# body"


def test_explore_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        explore.run(["--path", str(tmp_path / "missing")])

    assert excinfo.value.code == "target-directory-not-found"


def test_explore_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        explore.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-not-found"


def test_explore_returns_empty_when_adr_folder_missing(tmp_path):
    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    result = explore.run(["--path", str(tmp_path)])

    assert result["decisions"] == []
    # Usability audit round 3 (finding #5): "warnings" is present
    # unconditionally on every other command's result, even when empty --
    # explore omitted it entirely, breaking a generic wrapper that
    # assumed the key always exists.
    assert result["warnings"] == []


def test_explore_lists_recognized_and_unrecognized_files(tmp_path):
    config_dict = _default_config_dict()
    config = _write_repo(
        tmp_path,
        config_dict,
        {
            "ADR001V01-first-decision.md": _decision_text(
                parse_repo_config(json.dumps(config_dict)),
                number=1,
                title="First decision",
                version=1,
                status_create="Proposed",
                date_create=date(2026, 1, 1),
            ),
            "not-an-adr.md": "# just some markdown",
        },
    )

    result = explore.run(["--path", str(tmp_path)])
    by_name = {entry["filename"]: entry for entry in result["decisions"]}

    assert by_name["ADR001V01-first-decision.md"]["scheme"] == "current"
    assert by_name["ADR001V01-first-decision.md"]["number"] == 1
    assert by_name["ADR001V01-first-decision.md"]["title"] == "first-decision"
    assert by_name["ADR001V01-first-decision.md"]["header"]["is_valid"] is True
    assert by_name["ADR001V01-first-decision.md"]["header"]["status_create"] == "Proposed"
    assert by_name["ADR001V01-first-decision.md"]["header"]["date_create"] == "2026-01-01"
    # Usability audit A1: the full path, not just the bare filename -- an
    # agent needs this to act on the entry (--file on approve/reject/...)
    # without re-deriving folder/filename itself, which isn't safe under a
    # recursive scan that could have subfolders.
    assert by_name["ADR001V01-first-decision.md"]["path"] == str(
        tmp_path / config_dict["folderadr"] / "ADR001V01-first-decision.md"
    )

    assert by_name["not-an-adr.md"]["scheme"] is None
    assert by_name["not-an-adr.md"]["number"] == 0
    assert by_name["not-an-adr.md"]["header"]["is_valid"] is False


def test_explore_reports_encoding_repair_for_a_file_with_invalid_utf8_bytes(tmp_path):
    """Observability audit: explore already tolerates invalid UTF-8 bytes
    (Fase 4, confirmed live to match the real tool) but never told the
    caller a file needed repair -- the most natural place for this,
    since explore's whole purpose is giving an agent visibility into
    repository state."""
    config_dict = _default_config_dict()
    config = _write_repo(
        tmp_path,
        config_dict,
        {
            "ADR001V01-clean.md": _decision_text(
                parse_repo_config(json.dumps(config_dict)), number=1, title="Clean", version=1
            ),
        },
    )
    dirty_path = tmp_path / config.folderadr / "ADR002V01-dirty.md"
    with open(dirty_path, "w", encoding="utf-8", newline="") as handle:
        handle.write(_decision_text(config, number=2, title="Dirty", version=1))
    with open(dirty_path, "ab") as handle:
        handle.write(b"\r\nInvalid byte: \xa4 end.\r\n")

    result = explore.run(["--path", str(tmp_path)])

    by_name = {entry["filename"]: entry for entry in result["decisions"]}
    assert by_name["ADR001V01-clean.md"]["header"]["encoding_repaired"] is False
    assert by_name["ADR002V01-dirty.md"]["header"]["encoding_repaired"] is True


def test_explore_exposes_scope_and_domain(tmp_path):
    """Fidelity audit F14: the real tool's own report has Scope/Domain
    columns; adrpy's JSON dropped both entirely."""
    config_dict = _default_config_dict()
    _write_repo(
        tmp_path,
        config_dict,
        {
            "ADR001V01-first-decision.md": _decision_text(
                parse_repo_config(json.dumps(config_dict)),
                number=1,
                title="First decision",
                version=1,
                scope="Data",
                domain="Backend",
            ),
        },
    )

    result = explore.run(["--path", str(tmp_path)])

    entry = result["decisions"][0]
    assert entry["header"]["scope"] == "Data"
    assert entry["header"]["domain"] == "Backend"


def test_explore_sorts_by_validity_then_migrated_then_descending_numbers(tmp_path):
    config_dict = _default_config_dict()
    config = parse_repo_config(json.dumps(config_dict))
    decisions = {
        "ADR001V01-old-version.md": _decision_text(config, number=1, title="Old", version=1),
        "ADR001V02-new-version.md": _decision_text(config, number=1, title="New", version=2),
        "unrecognized.md": "not a header at all",
    }
    _write_repo(tmp_path, config_dict, decisions)

    result = explore.run(["--path", str(tmp_path)])
    order = [entry["filename"] for entry in result["decisions"]]

    assert order == [
        "ADR001V02-new-version.md",
        "ADR001V01-old-version.md",
        "unrecognized.md",
    ]


def test_explore_recognizes_legacy_scheme_too(tmp_path):
    config_dict = _default_config_dict()
    config_dict["migrationpattern"] = "N00:04T04"
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")
    (adr_dir / "0001UsePostgreSQL.md").write_text("# legacy content, no header yet", encoding="utf-8")
    with open(adr_dir / "ADR002V01-current-scheme.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(_decision_text(config, number=2, title="Current scheme", version=1))

    result = explore.run(["--path", str(tmp_path)])
    by_name = {entry["filename"]: entry for entry in result["decisions"]}

    assert by_name["0001UsePostgreSQL.md"]["scheme"] == "legacy"
    assert by_name["0001UsePostgreSQL.md"]["number"] == 1
    assert by_name["0001UsePostgreSQL.md"]["title"] == "UsePostgreSQL"
    assert by_name["ADR002V01-current-scheme.md"]["scheme"] == "current"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_explore_reports_a_candidate_excluded_via_a_windows_junction(tmp_path):
    """Round 4 observability audit, Finding 3: explore's own docstring
    promises "a file matching neither [naming scheme] still appears in
    the report, never dropped silently" -- but a file excluded via
    is_within (e.g. behind a junction escaping the folder) genuinely was
    dropped silently from that same report, by a different mechanism the
    promise didn't cover."""
    config = _write_repo(tmp_path, _default_config_dict(), {})
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "ADR009V01-victim-outside-the-repo.md").write_text(
        _decision_text(config, number=9, title="Victim outside the repo", version=1), encoding="utf-8"
    )
    adr_dir = tmp_path / config.folderadr
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    payload = explore.run(["--path", str(tmp_path)])

    assert payload["decisions"] == []
    assert len(payload["warnings"]) == 1
    assert "escapes the repository boundary" in payload["warnings"][0]


def test_explore_is_best_effort_when_one_file_is_persistently_unreadable(tmp_path, monkeypatch):
    """Round 7 resilience audit, Finding 1 (High): _build_entry's own
    raw_bytes = path.read_bytes() had no tolerance at all, transient or
    persistent -- unlike every other decision-file read in this codebase
    (read_header_lines, read_lines_with_report), which retries a
    transient PermissionError via the shared io_retry helper. One
    genuinely unreadable file (locked by an editor, backup tool, or
    antivirus -- an ordinary occurrence in a folder of Markdown files
    people also open by hand) used to kill the ENTIRE inventory with a
    bare io-error, discarding every other, perfectly readable file too.
    This is the same failure class round 6 already fixed for unreadable
    *subdirectories* -- explore should be just as best-effort about a
    single unreadable *file*."""
    config_for_text = parse_repo_config(json.dumps(_default_config_dict()))
    _write_repo(
        tmp_path,
        _default_config_dict(),
        {
            "ADR001V01-readable.md": _decision_text(config_for_text, number=1, title="Readable", version=1),
            "ADR002V01-locked.md": _decision_text(config_for_text, number=2, title="Locked", version=1),
        },
    )

    from pathlib import Path as PathType

    real_read_bytes = PathType.read_bytes

    def flaky_read_bytes(self, *args, **kwargs):
        if self.name == "ADR002V01-locked.md":
            raise PermissionError("Access is denied")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(PathType, "read_bytes", flaky_read_bytes)

    payload = explore.run(["--path", str(tmp_path)])

    filenames = {entry["filename"] for entry in payload["decisions"]}
    assert filenames == {"ADR001V01-readable.md"}
    assert any("ADR002V01-locked.md" in w for w in payload["warnings"])


def test_explore_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    exit_code = main(["explore", "--path", str(tmp_path)])

    assert exit_code == EXIT_SUCCESS


def test_explore_accepts_short_flag_end_to_end_through_main(tmp_path):
    """Fidelity audit F10: real adrplus's -p; end-to-end through main(),
    not just parse_flags in isolation."""
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    assert main(["explore", "-p", str(tmp_path)]) == EXIT_SUCCESS
