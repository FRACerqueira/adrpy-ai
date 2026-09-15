import json

from adrpy.cli import init, migrate, new
from adrpy.core.config import parse_repo_config
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
    init.run(["--path", str(tmp_path), "--file", str(config_file)])
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
