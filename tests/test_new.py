import json
import os
import subprocess
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from adrpy.cli import init, new
from adrpy.core.config import load_repo_config, parse_repo_config
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
    assert "|Created|Proposed (2026-01-01) <!-- Proposed -->|" in text
    assert "|Revision||" in text  # fixture's lenrevision == 0


def test_new_aborts_if_folderadr_changed_after_lock_acquired(tmp_path, monkeypatch):
    """The
    lock's own location is derived from a config read taken before the
    lock -- if a concurrent `config --folderadr` completes in the window
    before this call's own lock is actually acquired, it locks (and
    would write into) a directory the repository no longer uses.
    Reproduced live: an orphaned decision, two processes locking two
    different directories with zero exclusion between them. Simulates
    the race by returning a stale config from the bootstrap read while
    the file on disk already has the new value."""
    init.run(["--path", str(tmp_path)])
    stale_config = load_repo_config(tmp_path / "adr-config.adrplus")

    from adrpy.cli import config as config_module

    config_module.run(["--path", str(tmp_path), "--folderadr", "doc/adrB"])

    monkeypatch.setattr(
        new, "resolve_target_and_config", lambda path: (tmp_path, tmp_path / "adr-config.adrplus", stale_config)
    )

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "Orphan me"])

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert excinfo.value.data == {"locked_folderadr": "doc/adr", "current_folderadr": "doc/adrB"}
    assert not (tmp_path / "doc" / "adr" / "ADR001V01-orphan-me.md").exists()
    assert list((tmp_path / "doc" / "adrB").glob("*.md")) == []


def test_new_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage."""
    _init_repo(tmp_path)
    real_atomic_write_text = new.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(new, "atomic_write_text", flaky_atomic_write_text)

    result = new.run(["--path", str(tmp_path), "--title", "Use PostgreSQL"])

    assert any("3 attempts" in w for w in result["warnings"])


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_new_reports_a_candidate_excluded_via_a_windows_junction(tmp_path):
    """Closes the class through
    one representative write command -- new calls scan_decisions
    directly (for next_number/title-uniqueness), the same mechanism
    scan_decisions/family_members/explore/migrate/init's own tests
    already cover."""
    _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    (outside_dir / "ADR009V01-victim.md").write_text("# Victim\n", encoding="utf-8")
    junction = adr_dir / "linked"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(outside_dir)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr

    result_data = new.run(["--path", str(tmp_path), "--title", "Use PostgreSQL"])

    assert any("escapes the repository boundary" in w for w in result_data["warnings"])


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
    # The colliding filename was only ever in
    # `detail` (stderr, free text), never in `data`.
    assert excinfo.value.data == {"existing_file": "ADR001V01-use-postgre-sql.md"}


def test_new_reports_the_colliding_filename_as_data_when_it_already_exists(tmp_path, monkeypatch):
    """Simulates the TOCTOU race file-already-exists actually defends
    against: a concurrent `new` call creates the file after this call's
    own scan already took its snapshot (the scan itself would otherwise
    always see any pre-existing file matching the naming scheme and bump
    next_number/find_by_unique_title past it -- there is no other way to
    reach this collision for `new` specifically, since its filename and
    its title-uniqueness key are derived from the same normalized
    title)."""
    _init_repo(tmp_path)
    colliding_path = tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"
    colliding_path.parent.mkdir(parents=True, exist_ok=True)
    colliding_path.write_text("already here", encoding="utf-8")

    from adrpy.cli import new as new_module

    monkeypatch.setattr(new_module, "scan_decisions", lambda *args, **kwargs: [])

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "Use PostgreSQL"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": "ADR001V01-use-postgre-sql.md"}


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


@pytest.mark.parametrize("flag", ["domain", "scope"])
def test_new_rejects_embedded_delimiter_in_domain_and_scope(tmp_path, flag):
    """--domain/--scope need their own '|'-rejection coverage, distinct
    from --title's: they go through the exact same reject_embedded_
    delimiter call one line below."""
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "Real Title", f"--{flag}", "bad|value"])

    assert excinfo.value.code == "field-contains-forbidden-character"


@pytest.mark.parametrize("flag", ["title", "domain", "scope"])
def test_new_rejects_a_whitespace_only_value(tmp_path, flag):
    """A whitespace-only value must not be written verbatim -- an
    unguarded 'new --title "   "' would create a file literally named
    'ADR001V01-   .md'."""
    _init_repo(tmp_path)
    args = ["--path", str(tmp_path), "--title", "Real Title"]
    if flag == "title":
        args = ["--path", str(tmp_path), "--title", "   "]
    else:
        args += [f"--{flag}", "   "]

    with pytest.raises(CommandError) as excinfo:
        new.run(args)

    assert excinfo.value.code == "field-is-blank"


def test_new_accepts_domain_and_scope_omitted(tmp_path):
    """Positive control: domain/scope default to '' when not provided at
    all -- the blank-content fix above must not reject that established
    sentinel."""
    _init_repo(tmp_path)

    result = new.run(["--path", str(tmp_path), "--title", "Real Title"])

    assert "created" in result


def test_new_cleans_up_orphaned_temp_files_left_by_an_interrupted_write(tmp_path):
    """cleanup_orphaned_temp_files existed and was tested in
    isolation, but no command ever called it -- a
    process killed between the temp write and os.replace left the orphan
    behind forever, no cleanup, no warning."""
    _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    orphan = adr_dir / "leftover.md.deadbeef.tmp"
    orphan.write_text("never committed")
    old_time = time.time() - 999
    os.utime(orphan, (old_time, old_time))

    result = new.run(["--path", str(tmp_path), "--title", "Triggers cleanup"])

    assert not orphan.exists()
    assert any("leftover.md.deadbeef.tmp" in warning for warning in result["warnings"])


def test_new_reports_a_reclaimed_stale_lock_as_a_warning(tmp_path):
    """acquire_repo_lock's own reclaim
    report (test_lock.py) must actually reach a real command's result,
    not just the lock module in isolation."""
    from adrpy.core.lock import LOCK_FILE_NAME

    _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    lock_path = adr_dir / LOCK_FILE_NAME
    lock_path.write_text(f"stale-token\n{time.time() - 999}")

    result = new.run(["--path", str(tmp_path), "--title", "Triggers reclaim"])

    assert any("stale" in warning.lower() for warning in result["warnings"])


def test_new_reports_no_warnings_on_a_clean_run(tmp_path):
    _init_repo(tmp_path)

    result = new.run(["--path", str(tmp_path), "--title", "Clean run"])

    assert result["warnings"] == []


def test_new_rejects_path_traversal_via_title(tmp_path):
    """build_filename embeds the (case-transformed)
    title verbatim into the filename, and case transforms don't touch '/'
    or '..'. Caught by reject_filesystem_unsafe_title before build_filename
    is ever called (a round-22 security finding: '/' is a filesystem-unsafe
    character in its own right, not just a path-traversal vector) -- the
    resolve_within guard used for the folder itself remains a second,
    independent line of defense against anything that check might miss."""
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "../../../outside"])

    assert excinfo.value.code == "field-contains-forbidden-character"
    assert not (tmp_path.parent / "outside.md").exists()
    assert not (tmp_path.parent.parent / "outside.md").exists()


def test_new_rejects_a_colon_in_title_instead_of_leaving_an_ntfs_ads_orphan(tmp_path):
    """A round-22 security finding, confirmed live before this fix existed:
    ':' is not an invalid Windows filename character, it is the NTFS
    Alternate-Data-Stream separator -- the temp file WRITE succeeds (it's
    interpreted as a stream on a base file NTFS auto-creates), only the
    final rename to the real name fails, and the error-path cleanup only
    removes the named stream it just wrote, leaving that auto-created base
    file behind as a permanent, 0-byte, un-cleanable orphan
    (cleanup_orphaned_temp_files only globs '*.tmp', which this leftover's
    name never matches, and it lacks '.md' too, so scan_decisions/explore
    never see it either). Now caught before any write is attempted."""
    _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        new.run(["--path", str(tmp_path), "--title", "evil:hidden"])

    assert excinfo.value.code == "field-contains-forbidden-character"
    adr_dir = tmp_path / "doc" / "adr"
    assert list(adr_dir.iterdir()) == []  # no orphan left behind


def test_new_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """This scan feeds both
    title-uniqueness (find_by_unique_title) and next-number allocation
    -- a hidden decision inside an unreadable subdirectory must never be
    silently treated as "not found", or a duplicate title/number could
    be created."""
    tmp_path = _init_repo(tmp_path)
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
        new.run(["--path", str(tmp_path), "--title", "Some decision"])

    assert excinfo.value.code == "new-scan-incomplete"
    assert not (adr_dir / "ADR001V01-some-decision.md").exists()


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
    """The reference tool's -p/-t/-d/-s/-r; end-to-end
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
