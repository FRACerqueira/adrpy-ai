import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

from adrpy.cli import config, init, migrate, new
from adrpy.core.config import load_repo_config, parse_repo_config
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


def test_migrate_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Unlike an unreadable FILE
    (migration-scan-failed, already fail-closed), an unreadable
    subdirectory must get the same fail-closed treatment as its
    file-level sibling, not merely a warning -- this scan feeds
    already-tool-created-adrs-exist, a real safety decision (a hidden
    already-migrated file inside it could make that check silently
    answer "no" when the true answer is "yes")."""
    tmp_path = _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001T01.md", "Legacy content\n")
    adr_dir = tmp_path / "doc" / "adr"
    blocked = adr_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-scan-incomplete"


def test_migrate_aborts_if_folderadr_changed_after_lock_acquired(tmp_path, monkeypatch):
    """Migrate's own bootstrap config read can go stale if a concurrent
    config edit changes folderadr before this call's own lock is
    actually acquired -- it would then lock, scan, and write against a
    directory the repository no longer uses."""
    _init_repo_with_pattern(tmp_path)
    stale_config = load_repo_config(tmp_path / "adr-config.adrplus")

    config.run(["--path", str(tmp_path), "--folderadr", "doc/adrB"])

    monkeypatch.setattr(
        migrate, "resolve_target_and_config", lambda path: (tmp_path, tmp_path / "adr-config.adrplus", stale_config)
    )

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert excinfo.value.data == {"locked_folderadr": "doc/adr", "current_folderadr": "doc/adrB"}


def test_migrate_reports_lock_lost_not_a_per_candidate_failure_when_the_lock_read_itself_fails(tmp_path, monkeypatch):
    """A persistent I/O failure reading
    the lock file during verify_still_held() must not escape as a bare
    PermissionError -- being an OSError but not a LockLostError, it
    would otherwise fall through migrate's own `except LockLostError`
    clause into the per-candidate `except (OSError, UnicodeError)`,
    misreporting a candidate that was never touched as individually
    "failed", then repeating the same misclassification for every
    remaining candidate. Handled at the source (RepoLock.verify_still_held
    itself): this is a clean migration-lock-lost, matching the command's
    own documented contract, and the loop stops immediately instead of
    repeating the misclassification."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001Decision.md", "# Decision One\n")
    _write_legacy_file(tmp_path, "0002Decision.md", "# Decision Two\n")

    from adrpy.core import lock as lock_module

    real_read_lock = lock_module._read_lock
    calls = {"n": 0}

    def flaky_read_lock(path):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("Access is denied")
        return real_read_lock(path)

    monkeypatch.setattr(lock_module, "_read_lock", flaky_read_lock)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-lock-lost"
    # Aborted on the very first candidate's own recheck -- no candidate was
    # ever attempted (results is empty), not one falsely marked "failed".
    assert excinfo.value.data["results"] == []


def test_migrate_scan_phase_read_failure_is_a_structured_command_error(tmp_path, monkeypatch):
    """The
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

    # The scan-phase read now goes through
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
    """The
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


def test_migrate_rejects_a_title_with_a_filesystem_unsafe_character_as_a_per_file_failure(tmp_path, monkeypatch):
    """A round-22 security finding: migrate's title is sourced from a raw,
    untrusted legacy filename, sliced positionally with zero character
    filtering (naming.parse_legacy_filename) -- unlike every other
    command's own title, it was never validated at all. A hostile legacy
    filename's own name could embed a filesystem-unsafe character (e.g.
    ':', an NTFS Alternate-Data-Stream separator, confirmed live via
    `new`/`version`/`revise`/`supersede` to leave a permanent orphan) --
    but such a character can't be embedded in a REAL filename on this
    platform (creating it collapses into a stream, confirmed live), so
    this drives the exact code path a hostile POSIX-sourced filename
    would, via a monkeypatched parse result, the same technique already
    used above for a non-OSError mid-loop failure. Must be a per-file
    failure (migrate is best-effort), not a whole-batch abort."""
    _init_repo_with_pattern(tmp_path)
    good_path = _write_legacy_file(tmp_path, "0001Good.md", "# Good\n")
    bad_path = _write_legacy_file(tmp_path, "0002Bad.md", "# Bad\n")

    from adrpy.cli import migrate as migrate_module
    from adrpy.core.naming import ParsedFileName

    real_parse_any_filename = migrate_module.parse_any_filename

    def flaky_parse(filename, config):
        found = real_parse_any_filename(filename, config)
        if found is None:
            return None
        scheme, parsed = found
        if parsed.number == 2:
            parsed = ParsedFileName(
                number=parsed.number, version=parsed.version, revision=parsed.revision, title="evil:hidden"
            )
        return scheme, parsed

    monkeypatch.setattr(migrate_module, "parse_any_filename", flaky_parse)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-write-failed"
    results = excinfo.value.data["results"]
    statuses = {r["file"]: r["status"] for r in results}
    assert statuses[str(good_path)] == "migrated"
    assert statuses[str(bad_path)] == "failed"
    bad_error = results[[r["file"] for r in results].index(str(bad_path))]["error"]
    assert "filesystem-unsafe" in bad_error.lower()


def test_migrate_rejects_a_title_made_only_of_separator_characters_as_a_per_file_failure(tmp_path, monkeypatch):
    """A round-23 security finding: to_case (core/casing.py) falls back to
    echoing its raw input unchanged when word-splitting finds nothing to
    transform, which happens exactly when the title is made entirely of
    whitespace/'_'/'-' -- reachable here via a raw, untrusted legacy
    filename whose title segment has this shape, same technique as the
    filesystem-unsafe-character test above. Must be a per-file failure
    (migrate is best-effort), not a whole-batch abort."""
    _init_repo_with_pattern(tmp_path)
    good_path = _write_legacy_file(tmp_path, "0001Good.md", "# Good\n")
    bad_path = _write_legacy_file(tmp_path, "0002Bad.md", "# Bad\n")

    from adrpy.cli import migrate as migrate_module
    from adrpy.core.naming import ParsedFileName

    real_parse_any_filename = migrate_module.parse_any_filename

    def flaky_parse(filename, config):
        found = real_parse_any_filename(filename, config)
        if found is None:
            return None
        scheme, parsed = found
        if parsed.number == 2:
            parsed = ParsedFileName(number=parsed.number, version=parsed.version, revision=parsed.revision, title="---")
        return scheme, parsed

    monkeypatch.setattr(migrate_module, "parse_any_filename", flaky_parse)

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
    # Was only `assert results[1]["error"]`
    # (truthiness), which would pass even with the wrong error text.
    assert "simulated disk failure" in results[1]["error"]

    # The files that succeeded really were migrated on disk, despite the
    # sibling failure and the overall command reporting success=False.
    assert "<!-- Migrated -->" in Path(processed[0]).read_text(encoding="utf-8")
    assert "<!-- Migrated -->" in Path(processed[2]).read_text(encoding="utf-8")


def test_migrate_write_phase_read_retries_a_transient_permission_error(tmp_path, monkeypatch):
    """The write-phase read
    of a candidate's own bytes had no retry tolerance, unlike this
    command's own SCAN-phase read of the exact same file a few dozen
    lines earlier (read_header_lines_with_report, already retried).
    Without the fix, a transient blip here permanently misclassifies the
    candidate as "failed" instead of retrying transparently like its
    sibling read already would -- in a one-time, largely irreversible
    operation."""
    _init_repo_with_pattern(tmp_path)
    target = _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    real_read_bytes = Path.read_bytes
    calls = {"count": 0}

    def flaky_read_bytes(self, *args, **kwargs):
        if self.name == target.name:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_read_bytes(self, *args, **kwargs)

    monkeypatch.setattr(Path, "read_bytes", flaky_read_bytes)

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(target)]
    assert calls["count"] == 3


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
    assert "|Created||" in text  # StatusCreate stays Unknown, per the reference tool
    assert "# Use PostgreSQL\n\n## Context\n\nWe need a database.\n" in text
    # No test pinned the exact
    # empty-list value on a genuine happy path, only that the key exists.
    assert result["warnings"] == []


def test_migrate_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
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
    """Regression, confirmed against a real run of the reference tool's
    own `migrate` command: the
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
    """Confirmed against the reference tool's own live behavior: it discards a
    leading UTF-8 BOM when reading the legacy file, so the migrated result
    never has one; this port preserved the raw bytes including the BOM, which
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
    # No install-level config either (conftest.py's autouse fixture
    # forces this deterministically -- see its own docstring).
    init.run(["--path", str(tmp_path)])  # default config has empty migrationpattern
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-pattern-not-configured"


def test_migrate_rejects_when_install_level_config_exists_but_its_own_pattern_is_empty(tmp_path, monkeypatch):
    """ADR002V01 part 3's own stated precondition: "if migrationpattern
    is empty in BOTH places" -- distinct from the install-level config
    not existing at all (test_migrate_rejects_when_pattern_not_configured
    only exercises the latter, via conftest.py's default)."""
    tmp_path = _init_repo_with_pattern(tmp_path, pattern="")
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    fallback_text = json.dumps(_seed_config_with_pattern(""))
    monkeypatch.setattr(migrate, "read_install_config_text", lambda: fallback_text)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-pattern-not-configured"


def test_migrate_falls_back_to_install_level_pattern_and_persists_it(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path, pattern="")
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    fallback_text = json.dumps(_seed_config_with_pattern("N00:04T04"))
    monkeypatch.setattr(migrate, "read_install_config_text", lambda: fallback_text)

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(tmp_path / "doc" / "adr" / "0001First.md")]
    persisted = load_repo_config(tmp_path / "adr-config.adrplus")
    assert persisted.migrationpattern == "N00:04T04"


def test_migrate_prefers_repository_pattern_over_install_level_fallback(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path, pattern="N00:04T04")
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    def _fail_if_called():
        raise AssertionError("install-level config must not be consulted when the repo's own pattern is set")

    monkeypatch.setattr(migrate, "read_install_config_text", _fail_if_called)

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(tmp_path / "doc" / "adr" / "0001First.md")]


def test_migrate_rejects_when_tool_created_adr_already_exists(tmp_path):
    _init_repo_with_pattern(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Already tool created"])
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "already-tool-created-adrs-exist"


def test_migrate_refuses_when_a_scanned_file_has_a_lossy_encoding(tmp_path):
    """The scan-phase
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
    """Migrate's own scan used to
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
    """Migrate's scan phase used to
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
    """Losing the lock between two
    candidates must raise with the `results` list attached, not bare --
    describe() promises it names every candidate's own outcome, even on
    failure. Distinct from a per-file OSError/UnicodeError (which
    correctly keeps the loop going, one candidate at a time): losing the
    lock is a whole-operation event, not a single file's own problem, so
    it must stop the loop outright instead of misreporting every
    untouched remaining candidate as individually 'failed'."""
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
    """Migrate must hold the SAME repository lock for its whole operation
    (scan through every write), not just around a single write --
    confirmed empirically (real thread interleaving) that holding no
    lock at all lets it silently erase a concurrent approve's
    already-committed write, even though approve correctly held the lock
    and its own verify_still_held() passed honestly: a missing lock on
    migrate's side would defeat ADR001's guarantee for a command that did
    everything right. Proves the guarantee holds: while migrate is
    paused mid-run (in its write loop), a separate attempt to acquire the
    same lock with a short wait_ceiling must time out."""
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
    """Migrate fails with migration-pattern-not-
    configured on any freshly-init'd repository (100% of the time, not an
    edge case) -- describe() never said so, so an agent only discovered
    this by trial and error."""
    assert "migrationpattern" in migrate.describe()["description"]


def test_migrate_describe_documents_the_persist_back_write_survives_a_later_failure():
    """The persist-back write commits before
    the scan/eligibility checks and is never rolled back if one of them
    later refuses the run -- describe() must say so explicitly, not just
    "no file is touched," which would misleadingly imply
    adr-config.adrplus itself was untouched too."""
    description = migrate.describe()["description"]
    assert "survives" in description
    assert "no decision file is touched" in description
