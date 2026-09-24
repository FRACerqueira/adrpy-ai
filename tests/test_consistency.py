import os
import re

import pytest

from adrpy.core import consistency
from adrpy.core.consistency import HINTS, check_repository, validate_repository
from adrpy.core.errors import CommandError, FailureCodes
from adrpy.core.header import build_header

from conftest import D, decision_record, make_repo

_INVARIANT_CODES = {
    FailureCodes.MERGE_CONFLICT_MARKERS,
    FailureCodes.NO_HEADER,
    FailureCodes.INVALID_HEADER,
    FailureCodes.INVALID_STATUS_COMBINATION,
    FailureCodes.DUPLICATE_NUMBER,
    FailureCodes.PENDING_DUPLICATE,
    FailureCodes.PENDING_NOT_LIVE,
    FailureCodes.SUPERSEDED_DUPLICATE,
    FailureCodes.SUPERSEDED_NOT_LIVE,
    FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR,
    FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR,
    FailureCodes.MULTIPLE_LIVE_SUCCESSORS,
    FailureCodes.SCAN_INCOMPLETE,
}

_MIGRATED = {"migrationpattern": "N00:04T04"}


def _errors(repo):
    return check_repository(repo.folder, repo.config)[1]


def _codes(repo):
    return [error["code"] for error in _errors(repo)]


def _raised(repo):
    with pytest.raises(CommandError) as excinfo:
        validate_repository(repo.folder, repo.config)
    assert excinfo.value.code == FailureCodes.REPOSITORY_INCONSISTENT
    return excinfo.value.data["errors"]


def _without_markers(text):
    return re.sub(r" <!-- (Proposed|Accepted|Rejected|Superseded) -->", "", text)


# ------------------------------------------------------------ consistent --


def test_a_consistent_repository_returns_its_snapshot(tmp_path):
    repo = make_repo(
        tmp_path,
        files=[
            D(1, state="superseded", successor=2),
            D(2, state="accepted", suffix=1),
            D(3, state="rejected"),
            D(3, version=2, state="accepted"),
            D(4, state="accepted"),
            D(4, version=2, state="proposed"),
            D(5, state="accepted"),
            D(5, version=2, state="rejected"),
            D(5, version=3, state="superseded", successor=6),
            D(6, state="proposed", suffix=5),
            D(7, state="rejected", suffix=4),
        ],
    )

    snapshot = validate_repository(repo.folder, repo.config)

    assert len(snapshot.decisions) == 11
    assert sorted(snapshot.by_number) == [1, 2, 3, 4, 5, 6, 7]
    assert [d.state for d in snapshot.by_number[5]] == ["accepted", "rejected", "superseded"]
    first = snapshot.by_number[1][0]
    assert (first.state, first.successor_ref, first.scheme, first.name.number) == ("superseded", 2, "current", 1)
    assert snapshot.by_number[2][0].successor_ref is None


def test_the_decision_model_is_frozen(tmp_path):
    repo = make_repo(tmp_path, files=[D(1)])
    decision = validate_repository(repo.folder, repo.config).decisions[0]

    with pytest.raises(AttributeError):
        decision.state = "accepted"


def test_a_missing_decisions_folder_is_an_empty_consistent_repository(tmp_path):
    repo = make_repo(tmp_path)
    repo.folder.rmdir()

    assert validate_repository(repo.folder, repo.config).decisions == ()


def test_a_markdown_file_without_an_adr_name_is_ignored(tmp_path):
    repo = make_repo(tmp_path, files=[D(1)])
    (repo.folder / "README.md").write_text("# not a decision\n<<<<<<< HEAD\n", encoding="utf-8")
    (repo.folder / "notes").mkdir()
    (repo.folder / "notes" / "index.md").write_text("junk", encoding="utf-8")

    assert len(validate_repository(repo.folder, repo.config).decisions) == 1


def test_an_adrplus_header_without_canonical_markers_passes(tmp_path):
    """AdrPlus 1.0.0 writes no `<!-- Status -->` marker: the status is read
    from the label text alone, and every state it names passes."""
    probe = make_repo(tmp_path / "probe")
    specs = [
        D(1, state="superseded", successor=2),
        D(2, state="accepted", suffix=1),
        D(3, state="proposed"),
        D(4, state="rejected"),
    ]
    files = []
    for spec in specs:
        text = build_header(probe.config, decision_record(probe.config, spec)) + "# body\n"
        spec.content = _without_markers(text)
        assert "<!-- Accepted -->" not in spec.content
        files.append(spec)
    repo = make_repo(tmp_path / "repo", files=files)

    snapshot = validate_repository(repo.folder, repo.config)

    assert [d.state for d in snapshot.decisions if d.name.number == 1] == ["superseded"]
    assert len(snapshot.decisions) == 4


def test_migrated_files_pass_in_every_state_the_tool_leaves_them(tmp_path):
    """migrate writes a placeholder (blank Created, blank Version cell);
    approve/reject/supersede then fill Changed/Superseded and keep Created
    blank."""
    repo = make_repo(
        tmp_path,
        config=_MIGRATED,
        files=[
            D(1, version=0, migrated=True, state="placeholder", filename="0001Legacy.md"),
            D(2, version=0, migrated=True, state="accepted", filename="0002Legacy.md"),
            D(3, version=0, migrated=True, state="rejected", filename="0003Legacy.md"),
            D(4, version=0, migrated=True, state="placeholder", change="Superseded", successor=6, filename="0004Legacy.md"),
            D(5, version=0, migrated=True, state="superseded", successor=7, filename="0005Legacy.md"),
            D(6, state="proposed", suffix=4),
            D(7, state="accepted", suffix=5),
            D(1, version=1, state="proposed"),
        ],
    )

    snapshot = validate_repository(repo.folder, repo.config)

    states = {(d.name.number, d.name.version): d.state for d in snapshot.decisions}
    assert states[(1, 0)] == "placeholder"
    assert states[(4, 0)] == "superseded"
    assert snapshot.by_number[1][0].scheme == "legacy"


def test_a_migrated_placeholder_is_not_a_pending_decision(tmp_path):
    repo = make_repo(
        tmp_path,
        config=_MIGRATED,
        files=[
            D(1, version=0, migrated=True, state="placeholder", filename="0001Legacy.md"),
            D(2, version=0, migrated=True, state="placeholder", filename="0002Legacy.md"),
            D(2, version=1, state="proposed"),
        ],
    )

    assert _codes(repo) == []


def test_a_rejected_successor_needs_no_back_pointer(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, state="accepted"), D(2, state="rejected", suffix=1)])

    assert _codes(repo) == []


# ---------------------------------------------------------------- header --


def test_merge_conflict_markers_in_the_header_are_reported_first_and_alone(tmp_path):
    probe = make_repo(tmp_path / "probe")
    text = build_header(probe.config, decision_record(probe.config, D(1))).splitlines()
    conflicted = "\n".join(["<<<<<<< HEAD", *text[:5], "=======", *text[:5], ">>>>>>> theirs", *text[5:]])
    repo = make_repo(tmp_path / "repo", files=[D(1, content=conflicted + "\n")])

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.MERGE_CONFLICT_MARKERS]
    assert errors[0]["file"] == str(repo.paths[0])
    assert errors[0]["hint"] == HINTS[FailureCodes.MERGE_CONFLICT_MARKERS]


@pytest.mark.parametrize("marker", ["<<<<<<< HEAD", ">>>>>>> branch"])
def test_each_merge_conflict_marker_is_recognized(tmp_path, marker):
    probe = make_repo(tmp_path / "probe")
    lines = build_header(probe.config, decision_record(probe.config, D(1, state="accepted"))).splitlines()
    lines.insert(4, marker)
    repo = make_repo(tmp_path / "repo", files=[D(1, content="\n".join(lines) + "\n")])

    assert _codes(repo) == [FailureCodes.MERGE_CONFLICT_MARKERS]


def test_a_setext_underline_alone_is_not_a_merge_conflict(tmp_path):
    # "=======" is also a Markdown setext heading underline; only a real
    # conflict opener or closer makes it a conflict separator.
    repo = make_repo(tmp_path, files=[D(1, content="Context\n=======\n\nWe chose X.\n")])

    assert _codes(repo) == [FailureCodes.NO_HEADER]


def test_a_decision_reached_twice_through_a_junction_is_counted_once(tmp_path):
    if os.name != "nt":
        pytest.skip("junctions are Windows-only; POSIX symlinked dirs are not descended")
    import subprocess

    repo = make_repo(tmp_path, files=[D(1, state="accepted")])
    team = repo.folder / "team"
    team.mkdir()
    moved = team / repo.paths[0].name
    repo.paths[0].rename(moved)
    subprocess.run(["cmd", "/c", "mklink", "/J", str(repo.folder / "alias"), str(team)], check=True, capture_output=True)

    snapshot, errors = check_repository(repo.folder, repo.config)

    assert errors == []
    assert len(snapshot.decisions) == 1
    assert snapshot.decisions[0].path == moved


def test_a_file_without_a_header_gets_the_migrate_hint(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, content="# Just a heading\n\nbody\n")])

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.NO_HEADER]
    assert "migrate" in errors[0]["hint"]


def test_a_damaged_header_is_invalid_with_its_parse_reason(tmp_path):
    probe = make_repo(tmp_path / "probe")
    lines = build_header(probe.config, decision_record(probe.config, D(1))).splitlines()
    lines[3] = "|File title md|Use: PostgreSQL|"
    repo = make_repo(tmp_path / "repo", files=[D(1, content="\n".join(lines) + "\n")])

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.INVALID_HEADER]
    detail = errors[0]["detail"]
    # Both the rule's code and its own message, which names the field.
    assert detail.startswith(FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER + ": ")
    assert len(detail) > len(FailureCodes.FIELD_CONTAINS_FORBIDDEN_CHARACTER) + 10


@pytest.mark.parametrize(
    "spec",
    [
        D(1, created="Accepted", changed=None),
        D(1, changed="Proposed"),
        D(1, changed="Superseded"),
        D(1, state="rejected", change="Superseded", successor=2),
        D(1, state="proposed", change="Superseded", successor=2),
        D(1, created=None, changed="Accepted"),
        D(1, created=None, changed=None),
        D(1, migrated=True, state="placeholder", changed="Rejected", change="Superseded", successor=2),
        D(1, migrated=True, state="placeholder", changed="Proposed"),
    ],
    ids=[
        "created-accepted",
        "changed-proposed",
        "changed-superseded",
        "rejected-then-superseded",
        "proposed-then-superseded",
        "blank-created-not-migrated",
        "all-blank-not-migrated",
        "migrated-rejected-then-superseded",
        "migrated-changed-proposed",
    ],
)
def test_a_status_combination_outside_the_closed_set_is_reported(tmp_path, spec):
    repo = make_repo(tmp_path, files=[spec])

    assert _codes(repo) == [FailureCodes.INVALID_STATUS_COMBINATION]


def test_a_superseded_cell_holding_another_status_is_outside_the_closed_set(tmp_path):
    probe = make_repo(tmp_path / "probe")
    text = build_header(probe.config, decision_record(probe.config, D(1, state="superseded", successor=2)))
    text = text.replace("Superseded (2026-01-01) <!-- Superseded --> : 002", "Accepted (2026-01-01) <!-- Accepted --> : 002")
    assert "<!-- Accepted --> : 002" in text
    repo = make_repo(tmp_path / "repo", files=[D(1, content=text + "# body"), D(2, suffix=1)])

    assert FailureCodes.INVALID_STATUS_COMBINATION in _codes(repo)


# ------------------------------------------------------------- numbering --


def test_two_files_with_the_same_number_and_version_are_a_duplicate(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, title="First"), D(1, title="Second", state="accepted")])

    errors = _raised(repo)

    duplicates = [error for error in errors if error["code"] == FailureCodes.DUPLICATE_NUMBER]
    assert len(duplicates) == 1
    assert sorted([duplicates[0]["file"], *duplicates[0]["related_files"]]) == sorted(str(p) for p in repo.paths)
    assert "Superseded" in duplicates[0]["hint"] and "suffix" in duplicates[0]["hint"]


def test_a_legacy_revision_zero_and_a_current_blank_revision_are_the_same_key(tmp_path):
    repo = make_repo(
        tmp_path,
        config={"migrationpattern": "N00:04T06V04:02"},
        files=[
            D(1, version=1, state="accepted", filename="000101Legacy.md"),
            D(1, version=1, state="accepted"),
        ],
    )

    assert FailureCodes.DUPLICATE_NUMBER in _codes(repo)


def test_different_revisions_of_one_version_are_not_duplicates(tmp_path):
    repo = make_repo(
        tmp_path,
        config={"lenrevision": 2},
        files=[D(1, revision=1, state="accepted"), D(1, revision=2, state="proposed")],
    )

    assert _codes(repo) == []


# ---------------------------------------------------------------- family --


def test_two_open_proposed_decisions_in_one_family(tmp_path):
    repo = make_repo(
        tmp_path, config={"lenrevision": 2}, files=[D(1, revision=1), D(1, revision=2)]
    )

    codes = _codes(repo)

    assert FailureCodes.PENDING_DUPLICATE in codes
    assert FailureCodes.PENDING_NOT_LIVE in codes


def test_a_proposed_decision_that_is_not_the_live_one(tmp_path):
    repo = make_repo(tmp_path, files=[D(1), D(1, version=2, state="accepted")])

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.PENDING_NOT_LIVE]
    assert errors[0]["file"] == str(repo.paths[0])
    assert errors[0]["related_files"] == [str(repo.paths[1])]


def test_a_proposed_decision_older_than_a_rejected_one_is_still_live(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, state="accepted"), D(1, version=2, state="rejected"), D(1, version=3)])

    assert _codes(repo) == []


# ------------------------------------------ the 4 states AdrPlus produces --


def test_adrplus_v01_superseded_next_to_v02_accepted(tmp_path):
    repo = make_repo(
        tmp_path,
        files=[D(1, state="superseded", successor=3), D(1, version=2, state="accepted"), D(3, suffix=1)],
    )

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.SUPERSEDED_NOT_LIVE]
    assert errors[0]["file"] == str(repo.paths[0])
    assert errors[0]["hint"] == HINTS[FailureCodes.SUPERSEDED_NOT_LIVE]


def test_adrplus_two_superseded_members_in_one_family(tmp_path):
    repo = make_repo(
        tmp_path,
        files=[
            D(1, state="superseded", successor=2),
            D(1, version=2, state="superseded", successor=2),
            D(2, suffix=1),
        ],
    )

    codes = _codes(repo)

    assert FailureCodes.SUPERSEDED_DUPLICATE in codes
    duplicate = next(e for e in _errors(repo) if e["code"] == FailureCodes.SUPERSEDED_DUPLICATE)
    assert duplicate["hint"] == HINTS[FailureCodes.SUPERSEDED_DUPLICATE]


def test_adrplus_two_live_successors_of_one_predecessor(tmp_path):
    repo = make_repo(
        tmp_path,
        files=[D(1, state="superseded", successor=2), D(2, suffix=1), D(3, state="accepted", suffix=1)],
    )

    errors = _raised(repo)

    live = [error for error in errors if error["code"] == FailureCodes.MULTIPLE_LIVE_SUCCESSORS]
    assert len(live) == 1
    assert sorted([live[0]["file"], *live[0]["related_files"]]) == [str(repo.paths[1]), str(repo.paths[2])]
    assert live[0]["hint"] == HINTS[FailureCodes.MULTIPLE_LIVE_SUCCESSORS]


def test_adrplus_superseded_pointing_at_a_rejected_successor(tmp_path):
    repo = make_repo(tmp_path, files=[D(1, state="superseded", successor=2), D(2, state="rejected", suffix=1)])

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR]
    assert errors[0]["file"] == str(repo.paths[0])
    assert errors[0]["hint"] == HINTS[FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR]


# -------------------------------------------------------------- supersede --


@pytest.mark.parametrize(
    "files",
    [
        [D(1, state="superseded", successor=9)],
        [D(1, state="superseded", successor=2), D(2)],
        [D(1, state="superseded", successor=2), D(2, suffix=3), D(3, state="accepted")],
    ],
    ids=["successor-missing", "successor-without-suffix", "suffix-names-another"],
)
def test_a_superseded_decision_must_point_at_a_successor_naming_it(tmp_path, files):
    repo = make_repo(tmp_path, files=files)

    errors = _errors(repo)

    assert FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR in [e["code"] for e in errors]
    first = next(e for e in errors if e["code"] == FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR)
    assert first["file"] == str(repo.paths[0])


def test_a_superseded_cell_with_a_non_numeric_reference_has_no_successor(tmp_path):
    probe = make_repo(tmp_path / "probe")
    text = build_header(probe.config, decision_record(probe.config, D(1, state="superseded", successor=2)))
    text = text.replace("<!-- Superseded --> : 002", "<!-- Superseded --> : two")
    repo = make_repo(tmp_path / "repo", files=[D(1, content=text + "# body\n"), D(2, suffix=1)])

    codes = _codes(repo)

    assert FailureCodes.SUPERSEDED_WITHOUT_SUCCESSOR in codes


def test_a_live_successor_without_a_predecessor_pointing_back(tmp_path):
    """An interrupted supersede: the successor was created, the
    predecessor never marked."""
    repo = make_repo(tmp_path, files=[D(1, state="accepted"), D(2, suffix=1)])

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.SUCCESSOR_WITHOUT_PREDECESSOR]
    assert errors[0]["file"] == str(repo.paths[1])


def test_a_suffix_naming_the_same_or_a_higher_number_is_not_a_successor(tmp_path):
    repo = make_repo(tmp_path, files=[D(2, state="accepted", suffix=2), D(3, state="accepted", suffix=5)])

    assert _codes(repo) == []


# ------------------------------------------------------------------- scan --


def test_an_unreadable_subdirectory_is_scan_incomplete(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, files=[D(1)])
    blocked = repo.folder / "restricted"
    blocked.mkdir()
    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    errors = _raised(repo)

    assert [error["code"] for error in errors] == [FailureCodes.SCAN_INCOMPLETE]
    assert str(blocked) in errors[0]["file"]


def test_an_unreadable_decision_file_is_scan_incomplete(tmp_path, monkeypatch):
    repo = make_repo(tmp_path, files=[D(1), D(2)])
    real_read = consistency.read_header_lines

    def flaky_read(path, *args, **kwargs):
        if path == repo.paths[1]:
            raise PermissionError(13, "Access is denied", str(path))
        return real_read(path, *args, **kwargs)

    monkeypatch.setattr(consistency, "read_header_lines", flaky_read)

    errors = _raised(repo)

    assert [(error["code"], error["file"]) for error in errors] == [(FailureCodes.SCAN_INCOMPLETE, str(repo.paths[1]))]


# ------------------------------------------------------------------ shape --


def test_errors_are_sorted_by_file_then_code_and_carry_the_same_keys(tmp_path):
    repo = make_repo(
        tmp_path,
        files=[
            D(3, content="no header\n"),
            D(1, state="superseded", successor=9),
            D(2, created="Accepted", changed=None),
            D(1, version=2, state="accepted"),
        ],
    )

    errors = _errors(repo)

    assert errors == sorted(errors, key=lambda error: (error["file"], error["code"]))
    assert all(set(error) == {"code", "file", "related_files", "detail", "hint"} for error in errors)
    assert _errors(repo) == errors


def test_every_invariant_code_has_one_static_hint():
    assert set(HINTS) == _INVARIANT_CODES
    assert all(hint.strip() for hint in HINTS.values())
