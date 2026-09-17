import os
import subprocess
import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, HeaderParseResult, build_header
from adrpy.core.lifecycle import (
    family_members,
    find_by_unique_title,
    ineligibility_reason_for_approve_or_reject,
    ineligibility_reason_for_supersede,
    ineligibility_reason_for_undo,
    ineligibility_reason_for_version_or_revise,
    load_target,
    next_number,
    read_body,
    read_header_lines,
    read_header_lines_with_report,
    reject_folderadr_change_if_decisions_exist,
    resolve_repo_and_target,
    rewrite_status_field,
    scan_decisions,
    validate_refdate_not_before,
    validate_refdate_not_in_future,
    verify_folderadr_unchanged_since_lock,
)

import json

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def test_validate_refdate_not_in_future_accepts_today():
    validate_refdate_not_in_future(date.today())


def test_validate_refdate_not_in_future_rejects_tomorrow():
    with pytest.raises(CommandError) as excinfo:
        validate_refdate_not_in_future(date.today() + timedelta(days=1))

    assert excinfo.value.code == "refdate-in-future"


def test_validate_refdate_not_before_accepts_same_day():
    validate_refdate_not_before(date(2026, 1, 1), date(2026, 1, 1))


def test_validate_refdate_not_before_rejects_earlier_date():
    with pytest.raises(CommandError) as excinfo:
        validate_refdate_not_before(date(2026, 1, 1), date(2026, 1, 2))

    assert excinfo.value.code == "refdate-before-history"


def test_next_number_is_one_when_no_decisions_exist(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    assert next_number(scan_decisions(tmp_path, config)) == 1


def test_next_number_and_unique_title_with_real_decisions(tmp_path):
    config_dict = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=3, title="Existing decision", version=1)
    with open(adr_dir / "ADR003V01-existing-decision.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    decisions = scan_decisions(adr_dir, config)

    assert next_number(decisions) == 4
    assert find_by_unique_title("Existing Decision", config, decisions) is not None
    assert find_by_unique_title("Existing decision", config, decisions) is not None
    assert find_by_unique_title("Totally different", config, decisions) is None


def test_resolve_repo_and_target_reports_when_no_adr_config_is_found_above(tmp_path):
    """Round 4 test-adequacy audit, Finding 8: cannot-determine-root-path
    (raised when find_repo_root walks all the way up without finding
    adr-config.adrplus) had zero coverage -- reachable from every one of
    the 6 status-transition commands via resolve_repo_and_target."""
    orphan_dir = tmp_path / "no-repo-here"
    orphan_dir.mkdir()
    target = orphan_dir / "ADR001V01-orphan.md"
    target.write_text("not a real decision", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        resolve_repo_and_target(target)

    assert excinfo.value.code == "cannot-determine-root-path"


@pytest.mark.parametrize(
    ("content", "expected_code"),
    [
        ("", "adr-file-empty"),
        ("|only one line|", "adr-file-too-short"),
    ],
)
def test_load_target_surfaces_the_specific_header_error_as_the_code(tmp_path, content, expected_code):
    """Usability audit A4: header.error is already a specific, correctly-
    computed reason (adr-file-empty, adr-header-title-not-found, ...);
    load_target discarded it behind a single fixed "header-invalid" code,
    forcing an agent to fall back to a stderr string it can't rely on."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    target = adr_dir / "ADR001V01-broken.md"
    target.write_text(content, encoding="utf-8")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        load_target(target)

    assert excinfo.value.code == expected_code


def test_load_target_reports_no_encoding_repair_for_a_clean_file(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Clean", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-clean.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body\n")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    *_rest, encoding_repaired = load_target(target)

    assert encoding_repaired is False


def test_load_target_reports_encoding_repair_when_body_has_invalid_utf8_bytes(tmp_path):
    """Observability audit: reading a file with invalid UTF-8 bytes (Fase
    4: tolerated, confirmed live to match the real tool) silently replaces
    them with U+FFFD -- nothing told the caller this happened, even though
    it's a real, permanent loss of the original bytes the moment the file
    is rewritten."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Dirty", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-dirty.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body\n")
    with open(target, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")
    (tmp_path / "adr-config.adrplus").write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")

    *_rest, encoding_repaired = load_target(target)

    assert encoding_repaired is True


def test_rewrite_status_field_returns_the_write_attempt_count(tmp_path):
    """Observability audit: rewrite_status_field discarded atomic_write_text's
    own attempt count -- callers (approve/reject/undo) had no way to
    surface a "this needed retries" warning."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing", version=1, status_create="Proposed")
    target = adr_dir / "ADR001V01-existing.md"
    with open(target, "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    from adrpy.core.header import parse_header
    from adrpy.core.lifecycle import read_lines_with_report
    from adrpy.core.naming import parse_any_filename

    lines, _encoding_repaired = read_lines_with_report(target)
    header = parse_header(lines, config)
    _, filename_info = parse_any_filename(target.name, config)

    _record, _content, attempts = rewrite_status_field(
        target, config, lines, header, filename_info, field="update", status="Accepted", refdate=date(2026, 1, 2)
    )

    assert attempts == 1


def _header(**overrides):
    defaults = dict(is_valid=True, status_create="Proposed", status_update=None, status_change=None)
    defaults.update(overrides)
    return HeaderParseResult(**defaults)


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": None}, None),
        ({"status_update": "Accepted"}, "already-accepted"),
        ({"status_update": "Rejected"}, "already-rejected"),
        ({"status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted"}, "not-proposed"),
        # Regression, audit round 2: a status_update value that is
        # structurally valid (one of the 4 configured status labels, so
        # header.is_valid stays True) but is neither "Accepted" nor
        # "Rejected" -- reachable via a hand-edited/corrupted file whose
        # "Changed" cell contains the "Proposed" or "Superseded" label
        # text. Confirmed against the real ApproveCommandHandler.cs:59
        # (`StatusUpdate == AdrStatus.Unknown`) and this project's own
        # pre-refactor boolean (`status_update is None`): BOTH require
        # status_update to be None to be eligible -- any other value,
        # known or not, must be ineligible. The granular-code refactor
        # only excluded "Accepted"/"Rejected" explicitly, silently
        # falling through to eligible for anything else.
        ({"status_update": "Proposed"}, "unexpected-status"),
        ({"status_update": "Superseded"}, "unexpected-status"),
    ],
)
def test_ineligibility_reason_for_approve_or_reject(header_kwargs, expected_reason):
    """Usability audit: replaces a single collapsed not-eligible-for-*
    boolean with the SPECIFIC observed state -- an agent needs to know
    whether a decision is already accepted, already rejected, or already
    superseded, since each calls for a different recovery action."""
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_approve_or_reject(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": "Rejected"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
    ],
)
def test_ineligibility_reason_for_undo(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_undo(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Rejected"}, "already-rejected"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
        # Regression, audit round 2: same class as approve_or_reject's own
        # case above, but here it's a mislabel rather than a false
        # eligibility -- ineligible either way, but calling a corrupted
        # "Superseded"-in-the-wrong-cell value "already-rejected" is wrong.
        ({"status_update": "Superseded"}, "unexpected-status"),
    ],
)
def test_ineligibility_reason_for_supersede(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_supersede(header) == expected_reason


@pytest.mark.parametrize(
    ("header_kwargs", "expected_reason"),
    [
        ({"status_update": "Accepted"}, None),
        ({"status_update": "Rejected"}, None),
        ({"status_update": None}, "still-proposed"),
        ({"status_update": "Accepted", "status_change": "Superseded"}, "already-superseded"),
        ({"status_create": "Accepted", "status_update": "Accepted"}, "not-proposed"),
        # Regression, audit round 2: mislabel, not a false-eligibility bug
        # here (the boolean outcome already matched) -- but "still-proposed"
        # is wrong for a status_update that isn't actually None.
        ({"status_update": "Superseded"}, "unexpected-status"),
    ],
)
def test_ineligibility_reason_for_version_or_revise(header_kwargs, expected_reason):
    header = _header(**header_kwargs)

    assert ineligibility_reason_for_version_or_revise(header) == expected_reason


def test_read_header_lines_does_not_read_the_whole_file(tmp_path):
    """Performance backlog item: family_members only ever needs the fixed
    12-line header to decide membership -- reading a potentially huge
    body just for that is wasted I/O, repeated for every sibling on every
    lifecycle check (approve/reject/undo/version/revise/supersede)."""
    header_lines = [f"line{i}" for i in range(12)]
    huge_body = "x" * (5 * 1024 * 1024)
    target = tmp_path / "big.md"
    target.write_text("\n".join(header_lines) + "\n" + huge_body, encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise AssertionError("read_header_lines must not read the whole file")

    with patch.object(Path, "read_text", boom), patch.object(Path, "read_bytes", boom):
        lines = read_header_lines(target, count=12)

    assert lines == header_lines


def test_read_header_lines_handles_a_file_shorter_than_the_header(tmp_path):
    target = tmp_path / "short.md"
    target.write_text("only\ntwo\n", encoding="utf-8")

    lines = read_header_lines(target, count=12)

    assert lines == ["only", "two"]


def test_read_header_lines_with_report_does_not_read_the_whole_file(tmp_path):
    """Round 4 performance front, Finding D: same bounded-read guarantee
    as read_header_lines, now also used by migrate's own scan phase."""
    header_lines = [f"line{i}" for i in range(12)]
    huge_body = "x" * (5 * 1024 * 1024)
    target = tmp_path / "big.md"
    target.write_text("\n".join(header_lines) + "\n" + huge_body, encoding="utf-8")

    def boom(self, *args, **kwargs):
        raise AssertionError("read_header_lines_with_report must not read the whole file")

    with patch.object(Path, "read_text", boom), patch.object(Path, "read_bytes", boom):
        lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert lines == header_lines
    assert encoding_repaired is False


def test_read_header_lines_with_report_flags_a_lossy_decode_within_the_header(tmp_path):
    target = tmp_path / "corrupt.md"
    with open(target, "wb") as handle:
        handle.write(b"line0\n")
        handle.write(b"Invalid byte here: \xa4 end.\n")
        handle.write("\n".join(f"line{i}" for i in range(2, 12)).encode("utf-8") + b"\n")

    lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert encoding_repaired is True
    assert "�" in lines[1]


def test_read_header_lines_with_report_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """Round 5 stability re-run, Finding 4: this read had no
    PermissionError tolerance at all, unlike the write side
    (atomic_write.py) and the lock-file read side (core/lock.py's own
    _read_lock), which both already retry this project's own documented
    Windows "pending delete"/sharing-violation contention window --
    measured live at ~0.2% of reads under real concurrent writers. Same
    shared helper (core/io_retry.py) as _read_lock now uses, not a
    fourth independent copy of the loop."""
    target = tmp_path / "flaky.md"
    header_lines = [f"line{i}" for i in range(12)]
    target.write_text("\n".join(header_lines) + "\n", encoding="utf-8")

    import builtins

    real_open = builtins.open
    calls = {"count": 0}

    def flaky_open(path, *args, **kwargs):
        if str(path) == str(target) and "rb" in args:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", flaky_open)

    lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert lines == header_lines
    assert encoding_repaired is False
    assert calls["count"] == 3


def test_read_header_lines_with_report_raises_when_the_permission_error_persists(tmp_path, monkeypatch):
    target = tmp_path / "flaky.md"
    target.write_text("line0\n", encoding="utf-8")

    import builtins

    real_open = builtins.open

    def always_denied(path, *args, **kwargs):
        if str(path) == str(target) and "rb" in args:
            raise PermissionError("Access is denied")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", always_denied)

    with pytest.raises(PermissionError):
        read_header_lines_with_report(target, count=12)


def test_read_lines_with_report_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """Same class as the header-read test above, for read_lines_with_report
    (used by read_target's own primary read on every per-file command)."""
    from adrpy.core.lifecycle import read_lines_with_report

    target = tmp_path / "flaky.md"
    target.write_text("body\n", encoding="utf-8")

    real_read_bytes = Path.read_bytes
    calls = {"count": 0}

    def flaky_read_bytes(self, *args, **kwargs):
        if self == target:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    lines, encoding_repaired = read_lines_with_report(target)

    assert lines == ["body"]
    assert encoding_repaired is False
    assert calls["count"] == 3


def test_read_header_lines_with_report_ignores_corruption_far_past_the_header(tmp_path):
    """The bounded read stops once it recovers `count` real lines --
    content genuinely never read is never decoded, so corruption placed
    well past the first read chunk cannot be flagged. (A corrupted byte
    immediately after the header, still inside the same first 4096-byte
    chunk for a small file, WOULD still surface here -- an accepted,
    harmless side effect of the chunk boundary, not a safety gap, since
    migrate's write phase never decodes body bytes either way; they pass
    through raw regardless of what this function reports.)"""
    header_lines = [f"line{i}" for i in range(12)]
    target = tmp_path / "body-corrupt.md"
    with open(target, "wb") as handle:
        handle.write(("\n".join(header_lines) + "\n").encode("utf-8"))
        handle.write(b"x" * 8192)  # push well past the first read chunk
        handle.write(b"\nInvalid byte far into the body: \xa4 end.\n")

    lines, encoding_repaired = read_header_lines_with_report(target, count=12)

    assert lines == header_lines
    assert encoding_repaired is False


def test_family_members_excludes_a_structurally_invalid_file(tmp_path):
    """Legacy-scheme census audit: family_members must apply
    counts_as_family_member (is_valid OR is_migrated), mirroring
    AdrService.ReadAllAdrByNumber -- a filename-matching file whose header
    doesn't parse at all (unmigrated legacy, or simply corrupt) must never
    be counted as a family member, regardless of which naming scheme
    matched its filename."""
    config_dict = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    config_dict["migrationpattern"] = "N00:04T04"
    config = parse_repo_config(json.dumps(config_dict))

    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    record = DecisionRecord(number=1, title="Existing decision", version=1, status_create="Proposed")
    with open(adr_dir / "ADR001V01-existing-decision.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    (adr_dir / "0001LegacyNotes.md").write_text("# Not a real header at all\n", encoding="utf-8")

    members = family_members(adr_dir, config, 1)

    assert len(members) == 1
    assert members[0][0].title == "existing-decision"


def test_scan_decisions_never_sees_the_lock_marker_file(tmp_path):
    """Harness Fase 4/6/7 requirement (flagged by the resilience audit as
    unchecked by any front): LOCK_FILE_NAME must never appear as an
    "unrecognized file" nor be mistaken for a naming-scheme candidate.
    Confirmed here as an explicit guarantee, not an accident of every
    rglob call happening to filter on "*.md" -- if that filter ever
    changed, this is the test that would catch a regression."""
    from adrpy.core.lock import LOCK_FILE_NAME

    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    (adr_dir / LOCK_FILE_NAME).write_text("holder-token\n123.0")

    assert scan_decisions(adr_dir, config) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_scan_decisions_ignores_files_reached_through_a_windows_junction(tmp_path):
    """Security audit F2: resolve_within only validates the repository
    root; rglob("*.md") happily descends into a Windows junction planted
    inside the decisions folder (no admin privilege required to create
    one, and Path.is_symlink() does NOT detect it). Confirmed live:
    `migrate` wrote a real AdrPlus header into a file OUTSIDE the repo
    through exactly this, and `next_number` was poisoned by the outside
    file's own (unrelated) sequence number."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / "repo" / config.folderadr
    adr_dir.mkdir(parents=True)

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    record = DecisionRecord(number=9, title="Victim outside the repo", version=1)
    with open(outside_dir / "ADR009V01-victim-outside-the-repo.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")

    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert not junction.is_symlink()  # confirms the audit's premise: junctions aren't symlinks

    decisions = scan_decisions(adr_dir, config)

    assert decisions == []
    assert next_number(decisions) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_scan_decisions_reports_an_excluded_candidate_when_given_a_warnings_list(tmp_path):
    """Round 4 observability audit, Finding 3: is_within deliberately never
    RAISES over an escaped candidate (a scan should keep going, not fail
    over one), but that's a decision about raising, not about reporting --
    every call site used to drop the exclusion with zero signal. An agent
    seeing an unexpected next_number, or an inventory that doesn't match
    what's physically listable in the folder, had no way to learn why."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / "repo" / config.folderadr
    adr_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    record = DecisionRecord(number=9, title="Victim outside the repo", version=1)
    with open(outside_dir / "ADR009V01-victim-outside-the-repo.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    warnings = []
    scan_decisions(adr_dir, config, warnings=warnings)

    assert len(warnings) == 1
    assert "escapes the repository boundary" in warnings[0]
    assert str(junction) in warnings[0]

    # Backward compatible: no warnings= at all (the default) never raises.
    assert scan_decisions(adr_dir, config) == []


def test_scan_decisions_warns_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Round 6 resilience re-run, Finding B, class closure: Path.rglob
    (which scan_decisions uses) silently swallows an OSError raised
    while walking a subtree -- a subfolder that becomes unreadable
    mid-scan used to just make the result set smaller, with zero
    signal. Every caller that passes warnings= now finds out."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    warnings = []
    scan_decisions(adr_dir, config, warnings=warnings)

    assert len(warnings) == 1
    assert "could not be scanned" in warnings[0]
    assert str(blocked) in warnings[0]


def test_scan_decisions_fails_closed_when_strict_and_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Round 8 stability audit, class closure: round 6's own fix only
    ever warned here, which round 8 found lets a hidden family member
    (in an unreadable subdirectory) silently defeat safety decisions
    built on top of this scan (family guards, next-number allocation),
    reproducing round 7's "two live successors" corruption with no
    concurrency needed at all. `strict=True` fails closed instead, for
    callers that need a trustworthy result rather than a best-effort
    listing."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        scan_decisions(adr_dir, config, strict=True, incomplete_code="probe-scan-incomplete")

    assert excinfo.value.code == "probe-scan-incomplete"
    assert str(blocked) in excinfo.value.data["unreadable"][0]


def test_family_members_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Round 8 stability audit, Finding 1, reproduced directly at the
    source: family_members feeds has_superseded_sibling/has_pending_
    sibling/latest_in_family in every per-file command's own family
    guard -- a hidden Superseded/Pending sibling inside an unreadable
    subdirectory must never be silently treated as "no such member"."""
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / config.folderadr
    adr_dir.mkdir(parents=True)
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        family_members(adr_dir, config, 1)

    assert excinfo.value.code == "family-scan-incomplete"


def test_reject_folderadr_change_if_decisions_exist_fails_closed_when_scan_incomplete(tmp_path, monkeypatch):
    """Round 6 resilience re-run, Finding B: unlike scan_decisions'
    own generic callers (a warning is enough there -- nothing unsafe
    happens from an under-reported inventory), this specific guard
    gates a real safety decision (round 5, Finding 5): whether a
    folderadr change is allowed to proceed. If the scan it depends on
    might have silently missed decisions hiding in an unreadable
    subdirectory, `existing == []` can no longer be trusted to mean
    "genuinely empty" -- fails closed instead of allowing an orphaning
    it could not actually rule out."""
    config = load_repo_config(FIXTURE_PATH)
    old_folder = tmp_path / config.folderadr
    old_folder.mkdir(parents=True)
    blocked = old_folder / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        reject_folderadr_change_if_decisions_exist(old_folder, config.folderadr, "doc/adrB", config)

    assert excinfo.value.code == "folderadr-change-scan-incomplete"
    assert excinfo.value.data["folderadr"] == config.folderadr
    assert str(blocked) in excinfo.value.data["unreadable"][0]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_family_members_forwards_the_warnings_list_to_its_own_scan(tmp_path):
    config = load_repo_config(FIXTURE_PATH)
    adr_dir = tmp_path / "repo" / config.folderadr
    adr_dir.mkdir(parents=True)
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    record = DecisionRecord(number=1, title="Victim outside the repo", version=1)
    with open(outside_dir / "ADR001V01-victim-outside-the-repo.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record) + "# body")
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    warnings = []
    family_members(adr_dir, config, 1, warnings=warnings)

    assert len(warnings) == 1
    assert "escapes the repository boundary" in warnings[0]


def test_verify_folderadr_unchanged_since_lock_returns_fresh_config_when_matching(tmp_path):
    """Round 6 stability re-run, root cause shared by 8 call sites: the
    lock's own location is derived from a config read taken before the
    lock -- this helper re-reads fresh right after acquiring it and
    confirms folderadr (what the lock's location was derived from)
    didn't drift underneath. The happy path: nothing changed, the fresh
    config is returned for the caller to use from then on."""
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_text(open(FIXTURE_PATH, encoding="utf-8").read(), encoding="utf-8")
    original = load_repo_config(config_path)

    result = verify_folderadr_unchanged_since_lock(config_path, original.folderadr)

    assert result.folderadr == original.folderadr


def test_verify_folderadr_unchanged_since_lock_raises_when_folderadr_changed(tmp_path):
    """Round 6 stability re-run: reproduces the class live -- a concurrent
    `config --folderadr` (or `init --seed`) completing between this call's
    own pre-lock bootstrap read and the moment it acquires the lock means
    the lock's own location is no longer the repository's real folderadr.
    Must abort with a structured, mappable error instead of silently
    scanning/writing against a directory the repository no longer uses."""
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["folderadr"] = "doc/adrB"
    config_path = tmp_path / "adr-config.adrplus"
    config_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        verify_folderadr_unchanged_since_lock(config_path, "doc/adr", warnings=["accumulated"])

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert excinfo.value.data == {"locked_folderadr": "doc/adr", "current_folderadr": "doc/adrB"}
    assert excinfo.value.warnings == ["accumulated"]


def test_read_body_returns_empty_string_when_there_is_no_body(tmp_path):
    """Round 4 test-adequacy audit, Finding 11: read_body's `if not
    body_lines: return ""` branch had zero coverage -- config.py's own
    schema documents an empty template as a legitimate, reachable state
    (`config.py`'s `template` field "may be empty"), but every existing
    fidelity test uses a non-empty body."""
    header_only_lines = [f"line{i}" for i in range(12)]

    assert read_body(header_only_lines) == ""


def test_read_body_joins_with_the_host_line_separator(tmp_path):
    header_and_body = [f"line{i}" for i in range(12)] + ["first body line", "second body line"]

    assert read_body(header_and_body) == "first body line" + os.linesep + "second body line" + os.linesep
