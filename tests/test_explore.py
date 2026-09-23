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
    # "warnings" is present
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
    # The full path, not just the bare filename -- an
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
    """Explore already tolerates invalid UTF-8 bytes
    But never told the
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
    """The reference tool's own report has Scope/Domain columns; this port's
    JSON dropped both entirely."""
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


def test_explore_reports_no_marker_label_mismatch_for_an_ordinary_decision(tmp_path):
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
                status_create="Proposed",
                date_create=date(2026, 1, 1),
            ),
        },
    )

    result = explore.run(["--path", str(tmp_path)])

    assert result["decisions"][0]["header"]["marker_label_mismatches"] == []


def test_explore_reports_a_marker_label_mismatch(tmp_path):
    """ADR004V01: end-to-end through `explore`, not just core/header.py's
    own unit tests -- a hand-edited visible label that now disagrees with
    the hidden marker must be visible in this report, per-file, since
    explore lists every decision rather than acting on one specific
    target."""
    config_dict = _default_config_dict()
    config = parse_repo_config(json.dumps(config_dict))
    text = _decision_text(
        config,
        number=1,
        title="Hand-edited decision",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
    )
    # Hand-edit only the visible label word on the Created row, leaving
    # the hidden marker untouched -- same construction as core/header.py's
    # own unit test for this exact scenario.
    assert f"{config.statusnew} (2026-01-01) <!-- Proposed -->" in text
    text = text.replace(config.statusnew, config.statusacc, 1)
    _write_repo(tmp_path, config_dict, {"ADR001V01-first-decision.md": text})

    result = explore.run(["--path", str(tmp_path)])

    assert result["decisions"][0]["header"]["status_create"] == "Proposed"
    assert result["decisions"][0]["header"]["marker_label_mismatches"] == ["status_create"]


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
    """Explore's own docstring
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
    """`_build_entry`'s own bounded header read
    has no tolerance at all, transient or persistent -- unlike every other
    decision-file read in this codebase, which retries a transient
    PermissionError via the shared io_retry helper. One genuinely
    unreadable file (locked by an editor, backup tool, or antivirus --
    an ordinary occurrence in a folder of Markdown files people also
    open by hand) must not kill the ENTIRE inventory with a bare
    io-error, discarding every other, perfectly readable file too --
    the same failure class already guarded against for unreadable
    *subdirectories*; explore should be just as best-effort about a
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

    import builtins

    real_open = builtins.open
    locked_path = tmp_path / config_for_text.folderadr / "ADR002V01-locked.md"

    def flaky_open(path, *args, **kwargs):
        if str(path) == str(locked_path) and "rb" in args:
            raise PermissionError("Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)

    payload = explore.run(["--path", str(tmp_path)])

    filenames = {entry["filename"] for entry in payload["decisions"]}
    assert filenames == {"ADR001V01-readable.md"}
    assert any("ADR002V01-locked.md" in w for w in payload["warnings"])


def test_explore_retries_a_transient_permission_error_instead_of_skipping_the_file(tmp_path, monkeypatch):
    """Does TWO
    things -- retries a TRANSIENT PermissionError, and treats a
    PERSISTENT one as a skippable, warned file. The Test above
    only proves the second half; this proves the first: a file that
    fails twice then succeeds must appear normally in `decisions`, with
    no warning at all, not be silently skipped."""
    config_for_text = parse_repo_config(json.dumps(_default_config_dict()))
    _write_repo(
        tmp_path,
        _default_config_dict(),
        {
            "ADR001V01-flaky.md": _decision_text(config_for_text, number=1, title="Flaky", version=1),
        },
    )

    import builtins

    real_open = builtins.open
    flaky_path = tmp_path / config_for_text.folderadr / "ADR001V01-flaky.md"
    calls = {"count": 0}

    def flaky_open(path, *args, **kwargs):
        if str(path) == str(flaky_path) and "rb" in args:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)

    payload = explore.run(["--path", str(tmp_path)])

    filenames = {entry["filename"] for entry in payload["decisions"]}
    assert filenames == {"ADR001V01-flaky.md"}
    assert payload["warnings"] == []
    assert calls["count"] == 3


def test_explore_does_not_read_the_whole_file(tmp_path, monkeypatch):
    """parse_header only ever consumes the first 12 lines of a
    candidate -- reading and decoding its ENTIRE content
    (path.read_bytes()) would be wasteful, and explore is the natural
    "safe first look" an AI agent would run against an unfamiliar/
    external repository, with no indication a matching file could be
    huge. Confirmed live: an 800MB matching file drove peak traced
    memory to ~2.5GB for that single candidate when read whole. Uses
    the same bounded header read every other bulk scan in this
    codebase already relies on -- same technique as read_header_lines' own
    test_read_header_lines_does_not_read_the_whole_file (test_lifecycle.py):
    Path.read_bytes/read_text must never be called at all, not merely
    "called with a small size" (a size-based guard alone would not
    catch a regression back to path.read_bytes(), which bypasses
    builtins.open entirely and would otherwise slip past a
    read-size-only check unnoticed)."""
    config_for_text = parse_repo_config(json.dumps(_default_config_dict()))
    _write_repo(
        tmp_path,
        _default_config_dict(),
        {
            "ADR001V01-big.md": _decision_text(config_for_text, number=1, title="Big", version=1),
        },
    )
    big_path = tmp_path / config_for_text.folderadr / "ADR001V01-big.md"
    with open(big_path, "ab") as handle:
        handle.write(b"x" * (5 * 1024 * 1024))  # 5MB body

    from pathlib import Path as PathType

    real_read_bytes = PathType.read_bytes
    real_read_text = PathType.read_text

    def boom_read_bytes(self, *args, **kwargs):
        if str(self) == str(big_path):
            raise AssertionError(f"explore must not read the whole file via {self!r}")
        return real_read_bytes(self, *args, **kwargs)

    def boom_read_text(self, *args, **kwargs):
        if str(self) == str(big_path):
            raise AssertionError(f"explore must not read the whole file via {self!r}")
        return real_read_text(self, *args, **kwargs)

    monkeypatch.setattr(PathType, "read_bytes", boom_read_bytes)
    monkeypatch.setattr(PathType, "read_text", boom_read_text)

    payload = explore.run(["--path", str(tmp_path)])

    filenames = {entry["filename"] for entry in payload["decisions"]}
    assert filenames == {"ADR001V01-big.md"}


def test_explore_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    exit_code = main(["explore", "--path", str(tmp_path)])

    assert exit_code == EXIT_SUCCESS


def test_explore_accepts_short_flag_end_to_end_through_main(tmp_path):
    """The reference tool's -p; end-to-end through main(), not just
    parse_flags in isolation."""
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    config_dict = _default_config_dict()
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(config_dict), encoding="utf-8")

    assert main(["explore", "-p", str(tmp_path)]) == EXIT_SUCCESS


def test_explore_says_which_files_are_invalid_and_why(tmp_path):
    config = parse_repo_config(json.dumps(_default_config_dict()))
    valid = _decision_text(config, number=1, title="Valid", version=1, status_create="Proposed")
    damaged = valid.replace("|--|--|", "|-x|--|", 1)
    _write_repo(tmp_path, _default_config_dict(), {
        "ADR001V01-valid.md": valid,
        "ADR002V01-damaged.md": damaged,
        "ADR003V01-plain.md": "# Plain notes, no header\n",
    })

    decisions = explore.run(["--path", str(tmp_path)])["decisions"]

    states = {d["filename"]: (d["header"]["state"], d["header"]["invalid_reason"]) for d in decisions}
    assert states["ADR001V01-valid.md"] == ("valid", None)
    assert states["ADR002V01-damaged.md"] == ("adulterated", "adr-header-invalid-format")
    assert states["ADR003V01-plain.md"][0] == "no-header"



def test_explore_gives_the_reason_for_a_file_with_no_header(tmp_path):
    _write_repo(tmp_path, _default_config_dict(), {"ADR003V01-plain.md": "# Plain notes, no header\n"})

    decision = explore.run(["--path", str(tmp_path)])["decisions"][0]

    assert decision["header"]["state"] == "no-header"
    assert decision["header"]["invalid_reason"] == "adr-file-too-short"
