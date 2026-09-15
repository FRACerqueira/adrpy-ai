import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from adrpy.cli import init, new
from adrpy.core.config import parse_repo_config
from adrpy.core.errors import CommandError

import pytest

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _init_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    return tmp_path


def test_new_creates_first_decision(tmp_path):
    _init_repo(tmp_path)

    result = new.run(["--path", str(tmp_path), "--title", "Use PostgreSQL", "--refdate", "2026-01-01"])

    created = tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"
    assert result["created"] == str(created)
    assert result["status"] == "Proposed"

    raw = created.read_bytes()
    assert b"\r\r\n" not in raw  # regression: newline=os.linesep on already-CRLF content doubles every CR
    text = raw.decode("utf-8")
    assert "|File title md|Use PostgreSQL|" in text
    assert "|Created|Proposed (2026-01-01)|" in text
    assert "|Revision||" in text  # fixture's lenrevision == 0


def test_new_includes_revision_when_configured(tmp_path):
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["lenrevision"] = 2
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(data), encoding="utf-8")
    (tmp_path / "doc" / "adr").mkdir(parents=True)

    result = new.run(["--path", str(tmp_path), "--title", "Some decision"])

    text = Path(result["created"]).read_text(encoding="utf-8")
    assert "|Revision|01|" in text


def test_new_increments_number_and_scans_both_schemes(tmp_path):
    _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    result = new.run(["--path", str(tmp_path), "--title", "Second decision"])

    assert "ADR002V01-second-decision.md" in result["created"]


def test_new_rejects_duplicate_title(tmp_path):
    _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Use PostgreSQL"])

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "use postgre sql"])

    assert excinfo.value.code == "title-already-exists"


def test_new_rejects_refdate_in_the_future(tmp_path):
    _init_repo(tmp_path)
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "Future decision", "--refdate", future])

    assert excinfo.value.code == "refdate-in-future"


def test_new_rejects_invalid_refdate_format(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "Bad date", "--refdate", "01/01/2026"])

    assert excinfo.value.code == "refdate-invalid-format"


def test_new_rejects_embedded_delimiter_in_title(tmp_path):
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "Bad|title"])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_new_cleans_up_orphaned_temp_files_left_by_an_interrupted_write(tmp_path):
    """Observability + resilience audits (2 independent fronts, same
    finding): cleanup_orphaned_temp_files existed and was tested in
    isolation since Milestone 4, but no command ever called it -- a
    process killed between the temp write and os.replace left the orphan
    behind forever, no cleanup, no warning."""
    _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    orphan = adr_dir / "leftover.md.deadbeef.tmp"
    orphan.write_text("never committed")
    old_time = time.time() - 999
    os.utime(orphan, (old_time, old_time))

    new.run(["--path", str(tmp_path), "--title", "Triggers cleanup"])

    assert not orphan.exists()


def test_new_rejects_path_traversal_via_title(tmp_path):
    """Security audit F1: build_filename embeds the (case-transformed)
    title verbatim into the filename, and case transforms don't touch '/'
    or '..' -- confirmed live, a hostile --title escaped the repository
    entirely (e.g. 5 levels of "../" landed a file next to the sandbox
    root). The final path must be checked with the same resolve_within
    guard already used for the folder itself."""
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "../../../outside"])

    assert excinfo.value.code == "path-outside-repository"
    assert not (tmp_path.parent / "outside.md").exists()
    assert not (tmp_path.parent.parent / "outside.md").exists()


def test_new_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path / "missing"), "--title", "X"])

    assert excinfo.value.code == "target-directory-not-found"


def test_new_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "X"])

    assert excinfo.value.code == "config-not-found"


def test_new_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    _init_repo(tmp_path)

    exit_code = main(["new", "--path", str(tmp_path), "--title", "Through main"])

    assert exit_code == EXIT_SUCCESS
    assert (tmp_path / "doc" / "adr" / "ADR001V01-through-main.md").exists()


def test_new_accepts_short_flags_end_to_end_through_main(tmp_path):
    """Fidelity audit F10: real adrplus's -p/-t/-d/-s/-r; end-to-end
    through main(), not just parse_flags in isolation."""
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    _init_repo(tmp_path)

    exit_code = main(["new", "-p", str(tmp_path), "-t", "Short flags", "-d", "Backend", "-s", "Data"])

    assert exit_code == EXIT_SUCCESS
    created = tmp_path / "doc" / "adr" / "ADR001V01-short-flags.md"
    assert created.exists()
    text = created.read_text(encoding="utf-8")
    assert "|Domain|Backend|" in text
    assert "|Scope|Data|" in text
