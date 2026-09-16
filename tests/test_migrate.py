import json
import subprocess
import sys
import threading
import time
from pathlib import Path

from adrpy.cli import init, migrate, new
from adrpy.core.config import parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.lock import LockTimeoutError, acquire_repo_lock

import pytest

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _seed_config_with_pattern(pattern):
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["migrationpattern"] = pattern
    return data


def _init_repo_with_pattern(tmp_path, pattern="N00:04T04"):
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_seed_config_with_pattern(pattern)), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    return tmp_path


def _write_legacy_file(tmp_path, filename, content):
    # Raw bytes, not write_text: the default text-mode write would
    # translate every "\n" to os.linesep, silently hiding the exact bug
    # this file's own tests exist to catch (migrate must preserve the
    # original's own line endings byte-for-byte, never normalize them).
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / filename).write_bytes(content.encode("utf-8"))
    return adr_dir / filename


def test_migrate_scan_phase_read_failure_is_a_structured_command_error(tmp_path, monkeypatch):
    """Mechanism-correctness audit round 3 (resilience finding #2a): the
    initial directory scan's own read (building `entries`, used to decide
    eligibility) ran outside the per-candidate try/except entirely -- an
    OSError there (permission denied, a locked file, a network-drive
    hiccup) escaped as a raw OSError, discarding the orphan-cleanup
    warning already appended and skipping the deterministic per-file
    `results` reporting the whole best-effort redesign exists to
    guarantee."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001Good.md", "# Good\n")
    bad_path = _write_legacy_file(tmp_path, "0002Bad.md", "# Bad\n")

    # Round 4 performance fix: the scan-phase read now goes through
    # read_header_lines_with_report, a bounded read via a raw `open()`
    # handle, not Path.read_bytes/read_text -- patch the function itself
    # instead of the I/O primitive it happens to use internally.
    real_read_header_lines_with_report = migrate.read_header_lines_with_report

    def flaky_read_header_lines_with_report(path, *args, **kwargs):
        if path == bad_path:
            raise OSError("simulated read failure")
        return real_read_header_lines_with_report(path, *args, **kwargs)

    monkeypatch.setattr(migrate, "read_header_lines_with_report", flaky_read_header_lines_with_report)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-scan-failed"
    assert excinfo.value.data["unreadable_file"] == str(bad_path)


def test_migrate_non_oserror_failure_inside_the_write_loop_still_yields_a_result_entry(tmp_path, monkeypatch):
    """Mechanism-correctness audit round 3 (resilience finding #2b): the
    per-candidate loop only caught OSError -- a plausible non-OSError
    failure while building a candidate's new header (e.g. a
    UnicodeEncodeError from a title containing a lone surrogate) escaped
    the whole loop, discarding the results already collected for every
    file migrated successfully before it."""
    _init_repo_with_pattern(tmp_path)
    good_path = _write_legacy_file(tmp_path, "0001Good.md", "# Good\n")
    bad_path = _write_legacy_file(tmp_path, "0002Bad.md", "# Bad\n")

    from adrpy.cli import migrate as migrate_module

    real_build_header = migrate_module.build_header

    def flaky_build_header(config, record, migrated=False):
        if record.number == 2:
            raise UnicodeEncodeError("utf-8", "\udc80", 0, 1, "simulated surrogate")
        return real_build_header(config, record, migrated=migrated)

    monkeypatch.setattr(migrate_module, "build_header", flaky_build_header)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-write-failed"
    results = excinfo.value.data["results"]
    statuses = {r["file"]: r["status"] for r in results}
    assert statuses[str(good_path)] == "migrated"
    assert statuses[str(bad_path)] == "failed"


def test_migrate_continues_past_a_failed_file_and_reports_each_result(tmp_path, monkeypatch):
    """Design decision (2026-09-15), superseding the earlier fail-fast fix:
    migrate is best-effort per file -- one file's OSError must not block
    the rest, and the failure response must carry a deterministic
    per-file result array (every candidate, migrated or failed) instead
    of forcing the caller to infer what was never attempted from a
    migrated/failed_file pair that only covers the files seen so far."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    _write_legacy_file(tmp_path, "0002Second.md", "# Second\n")
    _write_legacy_file(tmp_path, "0003Third.md", "# Third\n")

    from adrpy.cli import migrate as migrate_module

    real_atomic_write_bytes = migrate_module.atomic_write_bytes
    processed = []

    def flaky_write(path, content):
        processed.append(str(path))
        if len(processed) == 2:
            raise OSError("simulated disk failure")
        return real_atomic_write_bytes(path, content)

    monkeypatch.setattr(migrate_module, "atomic_write_bytes", flaky_write)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-write-failed"
    # All 3 candidates were attempted, not just the ones up to the failure.
    assert len(processed) == 3

    results = excinfo.value.data["results"]
    statuses = {r["file"]: r["status"] for r in results}
    assert statuses[processed[0]] == "migrated"
    assert statuses[processed[1]] == "failed"
    assert statuses[processed[2]] == "migrated"
    # Test-adequacy audit round 3: was only `assert results[1]["error"]`
    # (truthiness), which would pass even with the wrong error text.
    assert "simulated disk failure" in results[1]["error"]

    # The files that succeeded really were migrated on disk, despite the
    # sibling failure and the overall command reporting success=False.
    assert "<!-- Migrated -->" in Path(processed[0]).read_text(encoding="utf-8")
    assert "<!-- Migrated -->" in Path(processed[2]).read_text(encoding="utf-8")


def test_migrate_happy_path_preserves_original_content(tmp_path):
    _init_repo_with_pattern(tmp_path)
    legacy_path = _write_legacy_file(
        tmp_path,
        "0001UsePostgreSQL.md",
        "# Use PostgreSQL\n\n## Context\n\nWe need a database.\n",
    )

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(legacy_path)]
    text = legacy_path.read_text(encoding="utf-8")
    assert "<!-- Migrated -->" in text
    assert "|File title md|UsePostgreSQL|" in text
    assert "|Created||" in text  # StatusCreate stays Unknown, per the real tool
    assert "# Use PostgreSQL\n\n## Context\n\nWe need a database.\n" in text
    # Round 4 test-adequacy audit, Finding 3: no test pinned the exact
    # empty-list value on a genuine happy path, only that the key exists.
    assert result["warnings"] == []


def test_migrate_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """Round 4 test-adequacy audit, Finding 4: retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage.
    migrate.py calls atomic_write_BYTES, not atomic_write_text."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001UsePostgreSQL.md", "# Use PostgreSQL\n")
    real_atomic_write_bytes = migrate.atomic_write_bytes

    def flaky_atomic_write_bytes(*args, **kwargs):
        real_atomic_write_bytes(*args, **kwargs)
        return 3

    monkeypatch.setattr(migrate, "atomic_write_bytes", flaky_atomic_write_bytes)

    result = migrate.run(["--path", str(tmp_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_migrate_preserves_original_line_endings_byte_for_byte(tmp_path):
    """Regression, confirmed against a real `adrplus migrate` run: the
    original body's own line endings (here, bare LF, unlike the header's
    host os.linesep) must pass through completely untouched -- only the
    header is new text. This is what caught the bug: an early version
    routed the concatenated content through atomic_write_text's newline
    normalization, which converted the body's LF into CRLF too."""
    tmp_path = _init_repo_with_pattern(tmp_path)
    body = "line one\nline two\n"
    legacy_path = _write_legacy_file(tmp_path, "0001LineEndings.md", body)

    migrate.run(["--path", str(tmp_path)])

    config = parse_repo_config(json.dumps(_seed_config_with_pattern("N00:04T04")))
    expected_header = build_header(config, DecisionRecord(number=1, title="LineEndings", version=0), migrated=True)
    assert legacy_path.read_bytes() == expected_header.encode("utf-8") + body.encode("utf-8")


def test_migrate_strips_a_leading_utf8_bom(tmp_path):
    """Fidelity audit F7: confirmed live -- the real adrplus discards a
    leading UTF-8 BOM when reading the legacy file, so the migrated result
    never has one; adrpy preserved the raw bytes including the BOM, which
    landed it in the MIDDLE of the file (after the new header, before the
    body) instead of not existing at all."""
    tmp_path = _init_repo_with_pattern(tmp_path)
    body_without_bom = "# BOM file\n"
    legacy_path = _write_legacy_file(tmp_path, "0001WithBom.md", body_without_bom)
    legacy_path.write_bytes(b"\xef\xbb\xbf" + body_without_bom.encode("utf-8"))

    migrate.run(["--path", str(tmp_path)])

    result_bytes = legacy_path.read_bytes()
    assert b"\xef\xbb\xbf" not in result_bytes
    assert result_bytes.endswith(body_without_bom.encode("utf-8"))


def test_migrate_multiple_files(tmp_path):
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    _write_legacy_file(tmp_path, "0002Second.md", "# Second\n")

    result = migrate.run(["--path", str(tmp_path)])

    assert len(result["migrated"]) == 2


def test_migrate_rejects_when_pattern_not_configured(tmp_path):
    init.run(["--path", str(tmp_path)])  # default config has empty migrationpattern
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-pattern-not-configured"


def test_migrate_rejects_when_tool_created_adr_already_exists(tmp_path):
    _init_repo_with_pattern(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Already tool created"])
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "already-tool-created-adrs-exist"


def test_migrate_refuses_when_a_scanned_file_has_a_lossy_encoding(tmp_path):
    """Round 4 observability audit, Finding 2, reproduced: the scan-phase
    read used `errors="replace"` with no signal at all -- a single
    invalid UTF-8 byte in an otherwise-valid, already-tool-created
    header's status-label cell made parse_header see it as invalid,
    bypassing the already-tool-created-adrs-exist safety check below and
    letting the file get a SECOND header stamped onto it (real,
    reproduced corruption -- the command reported success with
    warnings: [] and gave no indication anything was abnormal)."""
    _init_repo_with_pattern(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Already tool created"])
    target = tmp_path / "doc" / "adr" / "ADR001V01-already-tool-created.md"
    original_bytes = target.read_bytes()

    # Corrupt one byte inside the "Created" row's own status-label cell
    # (the exact class the audit reproduced), leaving the rest intact.
    corrupted = original_bytes.replace(b"Proposed", b"Propos\xa4d", 1)
    assert corrupted != original_bytes
    target.write_bytes(corrupted)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-scan-unreliable-encoding"
    assert excinfo.value.data == {"unreliable_files": [str(target)]}
    assert target.read_bytes() == corrupted  # never touched


def test_migrate_rejects_when_no_files_found(tmp_path):
    _init_repo_with_pattern(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "no-decisions-found"


def test_migrate_rejects_when_nothing_eligible(tmp_path):
    tmp_path = _init_repo_with_pattern(tmp_path)
    config = parse_repo_config(json.dumps(_seed_config_with_pattern("N00:04T04")))
    adr_dir = tmp_path / "doc" / "adr"
    record = DecisionRecord(number=1, title="Already migrated", version=0)
    with open(adr_dir / "ADR001V01-already-migrated.md", "w", encoding="utf-8", newline="") as handle:
        handle.write(build_header(config, record, migrated=True) + "# body")

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "no-eligible-files-to-migrate"


def test_migrate_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path / "missing")])

    assert excinfo.value.code == "target-directory-not-found"


def test_migrate_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-not-found"


def test_migrate_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    assert main(["migrate", "--path", str(tmp_path)]) == EXIT_SUCCESS


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_migrate_reports_a_candidate_excluded_via_a_windows_junction(tmp_path):
    """Round 4 observability audit, Finding 3: migrate's own scan used to
    drop an is_within-excluded candidate with zero signal, same as
    scan_decisions/explore."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001Good.md", "# Good\n")
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "0002Victim.md").write_text("# Victim\n", encoding="utf-8")
    adr_dir = tmp_path / "doc" / "adr"
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    result_data = migrate.run(["--path", str(tmp_path)])

    assert any("escapes the repository boundary" in w for w in result_data["warnings"])


def test_migrate_scan_phase_uses_the_bounded_header_read(tmp_path, monkeypatch):
    """Round 4 performance front, Finding D: migrate's scan phase used to
    read a candidate's ENTIRE content (read_lines_with_report) just to
    parse its 12-line header and check its encoding -- the same class of
    waste the round-1 performance fix already closed for family_members.
    Now wired to core.lifecycle.read_header_lines_with_report, the
    bounded equivalent."""
    _init_repo_with_pattern(tmp_path)
    legacy_path = _write_legacy_file(tmp_path, "0001Decision.md", "# Decision\n")

    from adrpy.cli import migrate as migrate_module
    from adrpy.core import lifecycle

    calls = []
    real = lifecycle.read_header_lines_with_report

    def spy(path, *args, **kwargs):
        calls.append(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(migrate_module, "read_header_lines_with_report", spy)

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"]
    assert legacy_path in calls


def test_migrate_aborts_and_reports_partial_results_when_the_lock_is_lost_mid_loop(tmp_path, monkeypatch):
    """Round 5 stability re-run, Finding 3: losing the lock between two
    candidates used to raise straight out of the per-candidate loop,
    discarding the `results` list describe() promises names every
    candidate's own outcome. Distinct from a per-file OSError/
    UnicodeError (which correctly keeps the loop going, one candidate at
    a time): losing the lock is a whole-operation event, not a single
    file's own problem, so it must stop the loop outright instead of
    misreporting every untouched remaining candidate as individually
    'failed'."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001Decision.md", "# Decision One\n")
    _write_legacy_file(tmp_path, "0002Decision.md", "# Decision Two\n")

    real_write = migrate.atomic_write_bytes
    calls = {"n": 0}

    def write_then_steal_lock(path, data):
        attempts = real_write(path, data)
        calls["n"] += 1
        if calls["n"] == 1:
            lock_path = tmp_path / "doc" / "adr" / ".adrpy.lock"
            lock_path.write_text(f"someone-else-entirely\n{time.time()}")
        return attempts

    monkeypatch.setattr(migrate, "atomic_write_bytes", write_then_steal_lock)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-lock-lost"
    assert len(excinfo.value.data["results"]) == 1
    assert excinfo.value.data["results"][0]["status"] == "migrated"
    assert calls["n"] == 1  # the second candidate's write was never attempted


def test_migrate_holds_the_repository_lock_for_its_whole_duration(tmp_path, monkeypatch):
    """Round 4 second corroboration pass (2/3 and 3/3, both independent):
    migrate held no lock at all -- confirmed empirically (real thread
    interleaving) to let it silently erase a concurrent approve's
    already-committed write, even though approve correctly held the lock
    and its own verify_still_held() passed honestly. migrate's missing
    lock defeated ADR001's guarantee for a command that did everything
    right. Proves migrate now holds the SAME repository lock for its
    whole operation (scan through every write), not just around a single
    write: while migrate is paused mid-run (in its write loop), a
    separate attempt to acquire the same lock with a short wait_ceiling
    must time out."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001Decision.md", "# Decision\n")

    entered = threading.Event()
    release = threading.Event()
    real_build_header = migrate.build_header

    def pausing_build_header(*args, **kwargs):
        entered.set()
        release.wait(timeout=5)
        return real_build_header(*args, **kwargs)

    monkeypatch.setattr(migrate, "build_header", pausing_build_header)

    migrate_thread = threading.Thread(target=lambda: migrate.run(["--path", str(tmp_path)]))
    migrate_thread.start()
    try:
        assert entered.wait(timeout=5), "migrate never reached its write loop"

        adr_dir = tmp_path / "doc" / "adr"
        with pytest.raises(LockTimeoutError):
            with acquire_repo_lock(adr_dir, wait_ceiling=0.3, poll_interval=0.05):
                pass
    finally:
        release.set()
        migrate_thread.join(timeout=5)
    assert not migrate_thread.is_alive()


def test_migrate_describe_documents_the_migrationpattern_precondition():
    """Usability audit A9: migrate fails with migration-pattern-not-
    configured on any freshly-init'd repository (100% of the time, not an
    edge case) -- describe() never said so, so an agent only discovered
    this by trial and error."""
    assert "migrationpattern" in migrate.describe()["description"]
