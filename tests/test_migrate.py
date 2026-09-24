import json
import os
import subprocess
import sys
from pathlib import Path

from adrpy.cli import init, migrate, new
from adrpy.core.config import load_repo_config, parse_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header

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
    """migrate's title is sourced from a raw,
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
    """to_case (core/casing.py) falls back to
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

    real_atomic_write_chunks = migrate_module.atomic_write_chunks
    processed = []

    def flaky_write(path, chunks_factory):
        processed.append(str(path))
        if len(processed) == 2:
            raise OSError("simulated disk failure")
        return real_atomic_write_chunks(path, chunks_factory)

    monkeypatch.setattr(migrate_module, "atomic_write_chunks", flaky_write)

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
    operation. ADR006V01: the write-phase read is now a stream opened via
    Path.open, sharing atomic_write_chunks' own single retry loop with
    the destination write -- each retried ATTEMPT re-opens the source
    fresh, so this still recovers from a transient PermissionError on the
    source open, just via one combined budget instead of two."""
    _init_repo_with_pattern(tmp_path)
    target = _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    real_open = Path.open
    calls = {"count": 0}

    def flaky_open(self, *args, **kwargs):
        if self.name == target.name and "rb" in args:
            calls["count"] += 1
            if calls["count"] < 3:
                raise PermissionError("Access is denied")
        return real_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", flaky_open)

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(target)]
    assert calls["count"] == 3


def test_migrate_write_does_not_read_the_whole_candidate_into_memory(tmp_path):
    """ADR006V01: without streaming, migrate's write phase would read
    the WHOLE candidate file into memory (`candidate_path.read_bytes()`)
    before concatenating a header onto it and writing the result -- a
    150MB candidate would measure a ~300MB peak-memory read. The header is already
    known to be schema-bounded (a few KB at most); only the candidate's
    own body content, unbounded, needs to stream."""
    from unittest.mock import patch

    _init_repo_with_pattern(tmp_path)
    huge_body = "x" * (20 * 1024 * 1024)  # 20MB, well past any reasonable chunk size
    legacy_path = _write_legacy_file(tmp_path, "0001Huge.md", huge_body)

    def boom(self, *args, **kwargs):
        raise AssertionError("migrate's write phase must not read the whole candidate at once")

    with patch.object(Path, "read_bytes", boom), patch.object(Path, "read_text", boom):
        result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(legacy_path)]
    text = legacy_path.read_text(encoding="utf-8")
    assert huge_body in text


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
    migrate.py calls atomic_write_CHUNKS (ADR006V01), not atomic_write_text."""
    _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001UsePostgreSQL.md", "# Use PostgreSQL\n")
    real_atomic_write_chunks = migrate.atomic_write_chunks

    def flaky_atomic_write_chunks(*args, **kwargs):
        real_atomic_write_chunks(*args, **kwargs)
        return 3

    monkeypatch.setattr(migrate, "atomic_write_chunks", flaky_atomic_write_chunks)

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

    # Round 39: a lossy byte only matters when it breaks the header. Here
    # the canonical marker still decides the status, so the header parses
    # and the already-tool-created check refuses -- still never touched.
    assert excinfo.value.code == "already-tool-created-adrs-exist"
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
    """Reading a candidate's ENTIRE content (read_lines_with_report) just to
    parse its 12-line header and check its encoding would be wasteful --
    the same class of waste already closed for family_members. Wired
    instead to core.header.read_header_lines_with_report, the
    bounded equivalent."""
    _init_repo_with_pattern(tmp_path)
    legacy_path = _write_legacy_file(tmp_path, "0001Decision.md", "# Decision\n")

    from adrpy.cli import migrate as migrate_module
    from adrpy.core import header

    calls = []
    real = header.read_header_lines_with_report

    def spy(path, *args, **kwargs):
        calls.append(path)
        return real(path, *args, **kwargs)

    monkeypatch.setattr(migrate_module, "read_header_lines_with_report", spy)

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"]
    assert legacy_path in calls


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


def test_a_successful_migrate_says_it_persisted_the_fallback_pattern(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path, pattern="")
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    monkeypatch.setattr(migrate, "read_install_config_text", lambda: json.dumps(_seed_config_with_pattern("N00:04T04")))

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrationpattern_persisted"] == "N00:04T04"


def test_a_refusal_after_the_persist_back_still_says_it_persisted_the_pattern(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path, pattern="")
    (tmp_path / "doc" / "adr").mkdir(parents=True, exist_ok=True)  # nothing to migrate
    monkeypatch.setattr(migrate, "read_install_config_text", lambda: json.dumps(_seed_config_with_pattern("N00:04T04")))

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.data["migrationpattern_persisted"] == "N00:04T04"


def test_no_persist_back_means_no_such_key(tmp_path):
    tmp_path = _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    result = migrate.run(["--path", str(tmp_path)])

    assert "migrationpattern_persisted" not in result



def test_an_interrupt_after_the_persist_back_still_says_it_persisted_the_pattern(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path, pattern="")
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    monkeypatch.setattr(migrate, "read_install_config_text", lambda: json.dumps(_seed_config_with_pattern("N00:04T04")))
    real_chunks = migrate.atomic_write_chunks

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(migrate, "atomic_write_chunks", interrupted)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "interrupted"
    assert excinfo.value.data["migrationpattern_persisted"] == "N00:04T04"


def test_an_interrupt_after_the_persist_back_keeps_the_warnings_already_collected(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path, pattern="")
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    monkeypatch.setattr(migrate, "read_install_config_text", lambda: json.dumps(_seed_config_with_pattern("N00:04T04")))
    monkeypatch.setattr(migrate, "orphan_cleanup_warning", lambda *_args: "an earlier warning")

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(migrate, "atomic_write_chunks", interrupted)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "interrupted"
    assert "an earlier warning" in excinfo.value.warnings


def test_a_per_file_failure_with_an_empty_message_still_says_what_failed(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    def failing_write(*args, **kwargs):
        raise OSError()

    monkeypatch.setattr(migrate, "atomic_write_chunks", failing_write)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-write-failed"
    assert excinfo.value.data["results"][0]["error"] == "OSError"


@pytest.mark.parametrize("damage", ["title", "first-line"])
def test_migrate_never_stamps_a_second_header_over_an_adulterated_one(tmp_path, damage):
    # A file that already carries this tool's header, damaged by hand, is
    # not "a file with no header": migrate refuses the whole run and names
    # it, instead of writing a new header on top of the broken one.
    tmp_path = _init_repo_with_pattern(tmp_path)
    legacy = _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")
    header = build_header(cfg, DecisionRecord(number=2, title="Second", version=1))
    lines = header.split("\n")
    if damage == "title":
        lines[3] = "broken title row"
    else:
        lines[0] = ""
    damaged = tmp_path / "doc" / "adr" / "0002Second.md"
    damaged.write_bytes(("\n".join(lines) + "# body\n").encode("utf-8"))
    before = {p.name: p.read_bytes() for p in (tmp_path / "doc" / "adr").glob("*.md")}

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-invalid-headers-exist"
    assert excinfo.value.data["files"] == [str(damaged)]
    assert {p.name: p.read_bytes() for p in (tmp_path / "doc" / "adr").glob("*.md")} == before


def test_a_legacy_file_with_an_ordinary_markdown_table_is_still_migrated(tmp_path):
    # Positive control for the refusal above: only rows this tool's header
    # writes count as its shape, not any table near the top of a file.
    tmp_path = _init_repo_with_pattern(tmp_path)
    legacy = _write_legacy_file(tmp_path, "0001First.md", "# First\n\n| Field | Value |\n|---|---|\n| a | b |\n")

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(legacy)]
    assert legacy.read_text(encoding="utf-8").count("|Adr-Plus ") == 1


def test_an_interrupt_mid_run_reports_the_files_already_migrated(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path)
    first = _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    second = _write_legacy_file(tmp_path, "0002Second.md", "# Second\n")
    real_chunks = migrate.atomic_write_chunks
    calls = {"count": 0}

    def interrupt_on_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise KeyboardInterrupt()
        return real_chunks(*args, **kwargs)

    monkeypatch.setattr(migrate, "atomic_write_chunks", interrupt_on_second)

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "interrupted"
    done = excinfo.value.data["results"]
    assert len(done) == 1 and done[0]["status"] == "migrated"
    assert done[0]["file"] in (str(first), str(second))


def test_a_legacy_three_column_table_with_short_dashes_is_still_migrated(tmp_path):
    # `|--|--|--|` starts like this tool's separator row but is not it.
    tmp_path = _init_repo_with_pattern(tmp_path)
    legacy = _write_legacy_file(tmp_path, "0001First.md", "# First\n\n|a|b|c|\n|--|--|--|\n|1|2|3|\n")

    result = migrate.run(["--path", str(tmp_path)])

    assert result["migrated"] == [str(legacy)]


def test_migrate_drops_every_leading_bom_of_a_legacy_file(tmp_path):
    tmp_path = _init_repo_with_pattern(tmp_path)
    legacy = _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    legacy.write_bytes(b"\xef\xbb\xbf\xef\xbb\xbf" + legacy.read_bytes())

    migrate.run(["--path", str(tmp_path)])

    assert b"\xef\xbb\xbf" not in legacy.read_bytes()


def test_migrate_refuses_over_a_tool_header_re_encoded_as_utf16(tmp_path):
    # PowerShell 5.1's Out-File and '>' write UTF-16LE with a BOM. Read as
    # UTF-8 the header no longer parses and its markers are split by NUL
    # bytes; it is still this tool's header, damaged -- never "no header",
    # or migrate would write a blank header over an Accepted decision.
    tmp_path = _init_repo_with_pattern(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Tool made"])
    tool_made = tmp_path / "doc" / "adr" / "ADR001V01-tool-made.md"
    tool_made.write_bytes(b"\xff\xfe" + tool_made.read_text(encoding="utf-8").encode("utf-16-le"))
    _write_legacy_file(tmp_path, "0002Legacy.md", "# Legacy\n")
    before = tool_made.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-invalid-headers-exist"
    assert excinfo.value.data["files"] == [str(tool_made)]
    assert tool_made.read_bytes() == before



@pytest.mark.parametrize("damage", ["lines-above", "no-field-row"])
def test_a_damaged_tool_header_is_recognized_past_line_two_and_by_its_separator(tmp_path, damage):
    tmp_path = _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")
    header = build_header(cfg, DecisionRecord(number=2, title="Second", version=1))
    lines = header.split("\n")
    if damage == "lines-above":
        lines = ["", "notes", "more notes"] + lines
    else:
        lines = [line.replace("|Adr-Plus Fields|", "|Fields|") for line in lines]
    damaged = tmp_path / "doc" / "adr" / "0002Second.md"
    damaged.write_bytes(("\n".join(lines) + "# body\n").encode("utf-8"))

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-invalid-headers-exist"
    assert excinfo.value.data["files"] == [str(damaged)]


def test_a_bom_at_a_later_chunk_boundary_is_body_content(tmp_path):
    from adrpy.core.atomic_write import STREAM_CHUNK_SIZE

    tmp_path = _init_repo_with_pattern(tmp_path)
    body = b"# First\n" + b"x" * (STREAM_CHUNK_SIZE - 8) + b"\xef\xbb\xbfafter"
    legacy = _write_legacy_file(tmp_path, "0001First.md", "")
    legacy.write_bytes(body)

    migrate.run(["--path", str(tmp_path)])

    assert legacy.read_bytes().endswith(b"\xef\xbb\xbfafter")


def test_an_interrupt_before_anything_was_written_propagates_as_is(tmp_path, monkeypatch):
    tmp_path = _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "0001First.md", "# First\n")

    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt()

    monkeypatch.setattr(migrate, "read_header_lines_with_report", interrupted)

    with pytest.raises(KeyboardInterrupt):
        migrate.run(["--path", str(tmp_path)])


def test_migrate_refuses_files_that_already_claim_to_be_successors(tmp_path):
    # Round 41 (H2): a supersede chain is a concept this tool creates; a
    # file claiming to be a successor before migration (a --NNN suffix) is
    # refused, naming every such file, and nothing is written.
    tmp_path = _init_repo_with_pattern(tmp_path)
    _write_legacy_file(tmp_path, "ADR004V01-delta.md", "# Delta\n")
    successor = _write_legacy_file(tmp_path, "ADR005V01-epsilon--004.md", "# Epsilon\n")
    before = {p.name: p.read_bytes() for p in (tmp_path / "doc" / "adr").glob("*.md")}

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "migration-successor-files-exist"
    assert excinfo.value.data["files"] == [str(successor)]
    assert {p.name: p.read_bytes() for p in (tmp_path / "doc" / "adr").glob("*.md")} == before


def test_a_tool_managed_repository_with_a_successor_is_refused_as_already_managed(tmp_path):
    # The successor refusal is about files arriving from outside; in a
    # repository the tool already manages, migrate must say so -- never
    # advise renaming the tool's own successor, which would break its chain.
    tmp_path = _init_repo_with_pattern(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Alpha", "--refdate", "2026-01-01"])
    from adrpy.cli import approve, supersede

    alpha = tmp_path / "doc" / "adr" / "ADR001V01-alpha.md"
    approve.run(["--file", str(alpha), "--refdate", "2026-01-02"])
    supersede.run(["--file", str(alpha), "--refdate", "2026-01-03"])

    with pytest.raises(CommandError) as excinfo:
        migrate.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "already-tool-created-adrs-exist"
