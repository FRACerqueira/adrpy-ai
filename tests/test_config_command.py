import os
import subprocess
import sys

from adrpy.cli import config, init, new
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError, UsageError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.naming import parse_any_filename

import pytest


def _init_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    return tmp_path


def _write_legacy_file(tmp_path, filename, content="Legacy content\n"):
    # Raw bytes, not new.run -- legacy-scheme files predate the tool and
    # are never created by it; mirrors test_migrate.py's own helper. A
    # name the current config already recognizes gets the migrated header
    # migrate itself would write (the filename is never renamed), so the
    # repository stays consistent: `config` validates it before changing
    # a guarded field.
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    repo_config = load_repo_config(tmp_path / ".adrpy.json")
    found = parse_any_filename(filename, repo_config)
    if found is not None:
        record = DecisionRecord(number=found[1].number, title=found[1].title, version=0)
        content = build_header(repo_config, record, migrated=True) + content
    (adr_dir / filename).write_bytes(content.encode("utf-8"))
    return adr_dir / filename


@pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions are Windows-specific")
def test_config_refuses_when_folderlog_is_a_junction_onto_folderadr(tmp_path):
    """A junction planted inside the repo tree, aliasing folderlog onto
    folderadr, is invisible to the schema-time guard -- config's own
    reject_aliased_repo_folders check must refuse before anything is
    written."""
    tmp_path = _init_repo(tmp_path)
    folderadr_dir = tmp_path / "doc" / "adr"
    folderlog_dir = tmp_path / "doc" / "decision-log"
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(folderlog_dir), str(folderadr_dir)], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "5"])

    assert excinfo.value.code == "folderadr-folderlog-alias-same-directory"
    assert load_repo_config(tmp_path / ".adrpy.json").lenseq == 3  # never committed


def test_config_changes_folderadr_when_the_old_folder_is_missing(tmp_path):
    """The folderadr/status/separator guards scan the OLD folder, and
    scan_tree treats a missing folder as
    unreadable -- config creates the old folder first, so a deleted one
    doesn't turn a legitimate change into folderadr-change-scan-incomplete."""
    tmp_path = _init_repo(tmp_path)
    import shutil

    shutil.rmtree(tmp_path / "doc" / "adr")

    result = config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert result["updated_fields"] == ["folderadr"]
    assert load_repo_config(tmp_path / ".adrpy.json").folderadr == "decisions"


def test_config_updates_a_single_field_and_preserves_the_rest(tmp_path):
    tmp_path = _init_repo(tmp_path)
    before = load_repo_config(tmp_path / ".adrpy.json")

    result = config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    assert result["updated_fields"] == ["prefix"]
    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.prefix == "DOC"
    assert after.folderadr == before.folderadr
    assert after.lenseq == before.lenseq


def test_config_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own "succeeded only after N attempts" message, end
    to end."""
    tmp_path = _init_repo(tmp_path)
    real_atomic_write_text = config.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(config, "atomic_write_text", flaky_atomic_write_text)

    result = config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    assert any("3 attempts" in w for w in result["warnings"])


def test_config_creates_the_decisions_folder_if_missing(tmp_path):
    """Nothing requires folderadr to exist before `config` runs (e.g. it
    was deleted, or folderadr was just repointed at a fresh path) --
    ensures the directory exists first, matching init's own precedent."""
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    import shutil

    shutil.rmtree(adr_dir)
    assert not adr_dir.is_dir()

    result = config.run(["--path", str(tmp_path), "--prefix", "XYZ"])

    assert result["updated_fields"] == ["prefix"]
    assert adr_dir.is_dir()


def test_config_updates_multiple_fields_at_once(tmp_path):
    tmp_path = _init_repo(tmp_path)

    result = config.run(
        ["--path", str(tmp_path), "--folderadr", "decisions", "--separator", "_", "--lenseq", "4"]
    )

    assert set(result["updated_fields"]) == {"folderadr", "separator", "lenseq"}
    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.folderadr == "decisions"
    assert after.separator == "_"
    assert after.lenseq == 4


def test_config_rejects_a_folderadr_change_when_decisions_already_exist(tmp_path):
    """A
    folderadr change is only valid when the OLD folder has no recognized
    decisions yet -- otherwise every existing decision becomes invisible
    at its old, still-real path, with nothing telling the caller. A
    structured, mappable error instead of a silent orphaning."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    before = load_repo_config(tmp_path / ".adrpy.json")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert excinfo.value.code == "folderadr-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"folderadr": "doc/adr", "existing_decisions": 1}
    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.folderadr == before.folderadr  # nothing was written


def test_config_folderadr_change_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """An unlistable subdirectory under the OLD folder fails closed through
    this real CLI command -- as the validator's scan-incomplete, since
    config validates the repository before a guarded change."""
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    blocked = adr_dir / "restricted"
    blocked.mkdir()
    before = load_repo_config(tmp_path / ".adrpy.json")

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    # config validates the repository before changing a guarded field: the
    # unlistable subdirectory is the validator's scan-incomplete.
    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]
    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.folderadr == before.folderadr  # nothing was written


def test_config_allows_a_folderadr_change_when_no_decisions_exist_yet(tmp_path):
    """Companion to the rejection test above: an empty (or missing)
    decisions folder has nothing to orphan, so the change must still go
    through, and the new folder must exist afterward."""
    tmp_path = _init_repo(tmp_path)

    result = config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert result["updated_fields"] == ["folderadr"]
    assert (tmp_path / "decisions").is_dir()


def test_config_rejects_a_folderadr_change_that_would_adopt_an_unrelated_file(tmp_path):
    """Pointing folderadr at a directory that already has an unrelated
    file matching the naming scheme silently adopted it as a decision,
    corrupting the next `new` call's own number allocation (ADR0008V01
    instead of ADR0001V01). Same shape guard as --separator's own
    adoption-check (ADR0004V02)."""
    tmp_path = _init_repo(tmp_path)
    new_folder = tmp_path / "unrelated-docs"
    new_folder.mkdir(parents=True)
    (new_folder / "ADR001V01-unrelated.md").write_bytes(b"hand written, never a real decision\n")
    before = load_repo_config(tmp_path / ".adrpy.json")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "unrelated-docs"])

    assert excinfo.value.code == "folderadr-change-would-adopt-unrelated-files"
    assert len(excinfo.value.data["adopted_files"]) == 1
    assert "ADR001V01-unrelated.md" in excinfo.value.data["adopted_files"][0]
    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.folderadr == before.folderadr  # nothing was written


def test_config_folderlog_change_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """The folderlog counterpart to
    test_config_folderadr_change_fails_closed_when_a_subdirectory_is_unreadable
    -- log-scan-incomplete (decision_log._existing_entries' own
    fail-closed path), reached through the CLI command, not just at the
    core level."""
    tmp_path = _init_repo(tmp_path)
    log_dir = tmp_path / "doc" / "decision-log"
    log_dir.mkdir(parents=True, exist_ok=True)
    blocked = log_dir / "restricted"
    blocked.mkdir()

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderlog", "other-log"])

    assert excinfo.value.code == "log-scan-incomplete"


def test_config_rejects_a_folderlog_change_when_entries_already_exist(tmp_path):
    """ADR0007V01: the folderlog counterpart to
    test_config_rejects_a_folderadr_change_when_decisions_already_exist
    above -- an existing decision-log entry would become invisible at
    its old, still-real path."""
    from adrpy.cli import log

    tmp_path = _init_repo(tmp_path)
    log.run(
        ["--path", str(tmp_path), "--classification", "scope-note", "--scope", "test", "--slug", "x",
         "--summary", "s", "--body", "b"]
    )
    before = load_repo_config(tmp_path / ".adrpy.json")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderlog", "doc/other-log"])

    assert excinfo.value.code == "folderlog-change-blocked-by-existing-entries"
    assert excinfo.value.data == {"folderlog": "doc/decision-log", "existing_entries": 1}
    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.folderlog == before.folderlog  # nothing was written


def test_config_allows_a_folderlog_change_when_no_entries_exist_yet(tmp_path):
    """Companion to the rejection test above: no decision-log entries
    yet means nothing to orphan, so the change must still go through."""
    tmp_path = _init_repo(tmp_path)

    result = config.run(["--path", str(tmp_path), "--folderlog", "doc/other-log"])

    assert result["updated_fields"] == ["folderlog"]


def test_config_rejects_a_folderlog_change_that_would_adopt_an_unrelated_file(tmp_path):
    """The folderlog counterpart to
    test_config_rejects_a_folderadr_change_that_would_adopt_an_unrelated_file
    -- pointing folderlog at a directory that already has a real-looking
    decision-log entry would silently adopt it into round allocation and
    INDEX.md."""
    from adrpy.cli import log as log_module

    tmp_path = _init_repo(tmp_path)
    unrelated = tmp_path / "unrelated-log"
    unrelated.mkdir(parents=True)
    (unrelated / "2026-09-18--scope-note--lock--first.md").write_text(
        log_module.build_entry_content("First", "Body."), encoding="utf-8"
    )

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderlog", "unrelated-log"])

    assert excinfo.value.code == "folderlog-change-would-adopt-unrelated-files"
    assert len(excinfo.value.data["adopted_files"]) == 1


def test_config_allows_a_folderlog_change_onto_a_directory_with_no_matching_content(tmp_path):
    """Companion to the rejection test above: a new folder that already
    exists but has nothing _existing_entries would even look at (its own
    scan is *.md only) must still go through. Unlike folderadr's own
    scan (which silently ignores a non-decision-shaped .md file),
    decision-log's own scan fails LOUDLY on any .md file it can't parse
    -- so a non-.md file is the true "no matching content" analog here,
    not an oddly-named .md one (see the sibling
    test_config_rejects_a_folderlog_change_onto_a_directory_with_an_unrecognized_md_file
    for that stricter case)."""
    tmp_path = _init_repo(tmp_path)
    unrelated = tmp_path / "unrelated-log"
    unrelated.mkdir(parents=True)
    (unrelated / "readme.txt").write_bytes(b"not even a .md file\n")

    result = config.run(["--path", str(tmp_path), "--folderlog", "unrelated-log"])

    assert result["updated_fields"] == ["folderlog"]


def test_config_rejects_a_folderlog_change_onto_a_directory_with_an_unrecognized_md_file(tmp_path):
    """decision-log's own scan (_existing_entries) is stricter than
    folderadr's: it fails LOUDLY (log-directory-contains-unrecognized-
    file) on any .md file that doesn't match the entry naming shape,
    rather than silently ignoring it -- and that propagates through the
    change guard, not just the scan itself."""
    tmp_path = _init_repo(tmp_path)
    unrelated = tmp_path / "unrelated-log"
    unrelated.mkdir(parents=True)
    (unrelated / "readme.md").write_bytes(b"not entry-shaped at all\n")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderlog", "unrelated-log"])

    assert excinfo.value.code == "log-directory-contains-unrecognized-file"


def test_config_allows_a_folderadr_change_onto_a_directory_with_no_matching_content(tmp_path):
    """Companion to the rejection test above: a new folder that already
    exists but has nothing that would newly parse as a decision must
    still go through -- this guard must not become a blanket refusal to
    ever repoint folderadr at a non-empty directory."""
    tmp_path = _init_repo(tmp_path)
    new_folder = tmp_path / "existing-notes"
    new_folder.mkdir(parents=True)
    (new_folder / "readme.md").write_bytes(b"not decision-shaped at all\n")

    result = config.run(["--path", str(tmp_path), "--folderadr", "existing-notes"])

    assert result["updated_fields"] == ["folderadr"]


def test_config_rejects_a_status_label_change_when_decisions_already_exist(tmp_path):
    """ADR0004V01: a status label change on a repository that already has
    recognized decisions can break a marker-less status cell's text
    match -- same shape guard as folderadr's own (without it, changing
    --statusnew made an existing decision is_valid: false)."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    before = load_repo_config(tmp_path / ".adrpy.json")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statusnew", "Draft"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["statusnew"], "existing_decisions": 1}
    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.statusnew == before.statusnew  # nothing was written


def test_config_rejects_a_separator_change_when_decisions_already_exist(tmp_path):
    """ADR0004V01: a separator change on a repository that already has
    recognized decisions breaks filename recognition entirely, with no
    marker option available for it at all (unlike status labels) -- this
    guard is `separator`'s only protection, permanently, once any
    decision exists."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--separator", "_"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["separator"], "existing_decisions": 1}


def test_config_rejects_multiple_guarded_fields_changed_at_once_naming_all_of_them(tmp_path):
    """A single call changing more than one guarded field at once must
    name every changed field in `data.changed_fields`, not just the
    first one found -- the one shared guard covers both fields with one
    scan, not independently per field."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statusacc", "Approved", "--separator", "_"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert set(excinfo.value.data["changed_fields"]) == {"statusacc", "separator"}


def test_config_rejects_separator_and_migrationpattern_together_on_a_mixed_scheme_repo(tmp_path):
    """ADR0004V02: the guard's blanket check (separator, among others) and
    its legacy-scoped check (migrationpattern) must be evaluated
    independently, not short-circuited against each other -- an if/elif
    chain (the legacy check skipped once the blanket check already
    matched) shows only on a mixed-scheme repository changing both fields
    at once. Both fields must be named here."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])  # current-scheme
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0002T02.md")  # legacy-scheme

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--separator", "_", "--migrationpattern", "N00:05T05"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert set(excinfo.value.data["changed_fields"]) == {"separator", "migrationpattern"}
    assert excinfo.value.data["existing_decisions"] == 2  # both decisions genuinely at risk (separator is blanket)


def test_config_rejects_a_statusrej_change_when_decisions_already_exist(tmp_path):
    """Same guard as statusnew's own test, but for statusrej -- the
    guard's own field tuple must cover all 4 status labels
    independently, not just the one field its first test happened to
    pick."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statusrej", "Denied"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["statusrej"], "existing_decisions": 1}


def test_config_rejects_a_statussup_change_when_decisions_already_exist(tmp_path):
    """Same as the statusrej test above, for statussup."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statussup", "Replaced"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["statussup"], "existing_decisions": 1}


def test_config_reports_the_correct_count_with_more_than_one_existing_decision(tmp_path):
    """`existing_decisions` is a real count, not a hardcoded 1: every
    other guard test creates exactly one decision."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    new.run(["--path", str(tmp_path), "--title", "Second decision"])
    new.run(["--path", str(tmp_path), "--title", "Third decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statusnew", "Draft"])

    assert excinfo.value.data == {"changed_fields": ["statusnew"], "existing_decisions": 3}


def test_config_migrationpattern_only_block_counts_only_legacy_scheme_decisions(tmp_path):
    """A MIXED-scheme repository changing ONLY migrationpattern: the count
    must reflect just the legacy-scheme subset (1), never the total (2). A
    scheme-homogeneous fixture could not tell 'a real total count' from 'a
    real count scoped to the right scheme'."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Current scheme decision"])
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0002T02.md")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--migrationpattern", "N00:05T05"])

    assert excinfo.value.data == {"changed_fields": ["migrationpattern"], "existing_decisions": 1}


def test_config_allows_a_migrationpattern_change_when_only_current_scheme_decisions_exist(tmp_path):
    """ADR0004V02: migrationpattern is only ever read by naming.py's
    parse_legacy_filename -- a repository with only current-scheme
    decisions has nothing that a migrationpattern change could break, so a
    blanket guard (ADR0004V01) would refuse this harmless change for no
    reason."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    result = config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])

    assert result["updated_fields"] == ["migrationpattern"]


def test_config_rejects_a_migrationpattern_change_when_a_legacy_decision_already_exists(tmp_path):
    """The mirror of the test above: migrationpattern change IS blocked
    once a legacy-scheme decision exists, since parse_legacy_filename
    re-derives that file's own number/version/revision by position and
    length from this exact field, read fresh on every parse."""
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0001T01.md")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--migrationpattern", "N00:05T05"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["migrationpattern"], "existing_decisions": 1}


def test_config_clears_migrationpattern_with_an_empty_value_when_no_legacy_decision_exists(tmp_path):
    """Owner decision: `--migrationpattern ""` clears the pattern -- the
    one optional flag whose empty value is a real value, not an omission."""
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    result = config.run(["--path", str(tmp_path), "--migrationpattern", ""])

    assert result["updated_fields"] == ["migrationpattern"]
    assert config.run(["--path", str(tmp_path)])["config"]["migrationpattern"] == ""


def test_config_refuses_to_clear_migrationpattern_while_a_legacy_decision_exists(tmp_path):
    """Clearing is a migrationpattern change like any other: the legacy
    decision would stop being recognized, so the existing guard refuses
    it and the config file is left untouched."""
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0001T01.md")
    config_file = tmp_path / ".adrpy.json"
    before = config_file.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--migrationpattern", ""])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["migrationpattern"], "existing_decisions": 1}
    assert config_file.read_bytes() == before


def test_config_rejects_a_separator_change_when_only_legacy_scheme_decisions_exist(tmp_path):
    """ADR0004V02: separator is only ever READ by naming.py's
    parse_filename (the current scheme), but that is not enough to scope
    the guard to current-scheme decisions only -- parse_any_filename
    tries the current scheme FIRST, so a separator value that happens to
    already appear in a legacy filename can make it newly match under
    parse_filename, silently reclassifying a legacy decision as
    current-scheme with a different number/title (under a guard scoped
    that way, the file's own scheme flipped on the next scan). So
    separator is blanket; only migrationpattern is genuinely safe to scope
    (naming.py's parse_filename never reads it, so it has no mirror
    reclassification risk)."""
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0001T01.md")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--separator", "_"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["separator"], "existing_decisions": 1}


def test_config_separator_change_does_not_silently_reclassify_a_legacy_file_as_current_scheme(tmp_path):
    """The reclassification risk itself: a legacy file whose name would
    parse as current-scheme under separator "_" makes that separator
    change refused, with nothing committed."""
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0001_MyTitle.md")

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--separator", "_"])

    # Nothing committed -- the file is still recognized under its
    # original scheme/identity, not silently reclassified.
    config_after = load_repo_config(tmp_path / ".adrpy.json")
    assert config_after.separator == "-"


def test_config_rejects_a_separator_change_that_would_adopt_an_unrelated_unrecognized_file(tmp_path):
    """Every check above is keyed on decisions already recognized under
    the OLD config -- none of them catch a file that ISN'T currently
    recognized by any scheme becoming newly recognized. An unrelated
    hand-written .md file (never created via `new`, no relationship to the
    decision lifecycle) sitting in the decisions folder must never be
    silently adopted as a genuine decision just because a separator change
    happens to make its own name parse."""
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / "ADR001V01_MyTitle.md").write_bytes(b"hand written, not a real decision file\n")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--separator", "_"])

    assert excinfo.value.code == "separator-change-would-adopt-unrelated-files"
    assert len(excinfo.value.data["adopted_files"]) == 1
    assert "ADR001V01_MyTitle.md" in excinfo.value.data["adopted_files"][0]
    # Nothing committed.
    config_after = load_repo_config(tmp_path / ".adrpy.json")
    assert config_after.separator == "-"


def test_config_allows_a_separator_change_that_adopts_nothing(tmp_path, monkeypatch):
    """Companion to the rejection test above: a separator change with no
    unrelated file anywhere that would newly parse under the new value
    must still go through -- this guard must not become a blanket
    refusal to ever change separator at all.

    An empty decisions folder (or a file that stays unrecognized under both
    separators) cannot tell "the adoption scan ran and correctly found
    nothing new" from "the adoption scan never ran at all": either way
    there is nothing to adopt. Proven instead via a call-count spy on the
    guard's filename recognition over the scan -- it runs twice for a
    successful separator change (once for `existing` under old_config,
    once for the adoption check under the separator-only config); a
    disabled adoption check would only run it once."""
    tmp_path = _init_repo(tmp_path)
    from adrpy.core import lifecycle as lifecycle_module

    real_recognized = lifecycle_module._recognized
    calls = []

    def counting_recognized(scan, config_used, warnings):
        calls.append(config_used.separator)
        return real_recognized(scan, config_used, warnings)

    monkeypatch.setattr(lifecycle_module, "_recognized", counting_recognized)

    result = config.run(["--path", str(tmp_path), "--separator", "_"])

    assert result["updated_fields"] == ["separator"]
    assert calls == ["-", "_"]  # existing (old_config) + the adoption check (separator-only config)


def test_config_separator_and_migrationpattern_change_together_does_not_cross_attribute_adoption(tmp_path):
    """An adoption check that scans with the FULL new config, instead of a
    separator-only one, would let a call changing both --separator and
    --migrationpattern at once get wrongly refused over files only
    migrationpattern's own (intentional) adoption would newly recognize --
    blaming separator for something it had no part in. This file's own name
    contains no "_" anywhere, so separator alone provably adopts nothing;
    only migrationpattern does, which must not trigger the separator-only
    adoption check."""
    tmp_path = _init_repo(tmp_path)
    _write_legacy_file(tmp_path, "0001UsePostgreSQL.md")

    result = config.run(["--path", str(tmp_path), "--separator", "_", "--migrationpattern", "N00:04T04"])

    assert set(result["updated_fields"]) == {"separator", "migrationpattern"}


def test_config_blocking_fields_check_wins_over_the_adoption_check_when_both_could_apply(tmp_path):
    """The adoption check is only ever
    reached once the blocking-fields check above it has already passed
    -- pins this precedence explicitly. An
    existing recognized decision blocks --statusnew outright; an
    unrelated file that WOULD genuinely be newly adopted by the same
    --separator change sits in the same folder (proven separately: it
    contains a digit run followed by "_", which parses as current-scheme
    only once separator becomes "_") -- but the call never reaches the
    adoption check at all, since blocking_fields already raises first,
    so only the blocking-fields error is ever seen."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])  # blocks statusnew unconditionally
    adr_dir = tmp_path / "doc" / "adr"
    (adr_dir / "0002_SomeTitle.md").write_bytes(b"not a decision\n")  # would be adopted by --separator _ alone

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statusnew", "Draft", "--separator", "_"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"


def test_config_migrationpattern_change_still_intentionally_adopts_legacy_files(tmp_path):
    """The adoption guard is deliberately scoped to `separator` only --
    migrationpattern recognizing a previously-unrecognized legacy file is
    that field's own documented, intentional purpose (ADR0002V01), not the
    bug this guard exists to close. A migrationpattern change that newly
    recognizes an existing hand-written file (with no other guarded field
    changing, and no already-recognized decision at risk) must still
    succeed."""
    tmp_path = _init_repo(tmp_path)
    _write_legacy_file(tmp_path, "0001T01.md")  # unrecognized: no migrationpattern configured yet

    result = config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])

    assert result["updated_fields"] == ["migrationpattern"]


def test_config_status_or_separator_change_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """status-or-separator-change-scan-incomplete (this guard's own
    fail-closed path) through the CLI, like the folderadr guard's own
    equivalent test."""
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
        config.run(["--path", str(tmp_path), "--statusnew", "Draft"])

    # As above: the validator's scan-incomplete, before the guard's own.
    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]


def test_config_allows_a_status_label_change_when_no_decisions_exist_yet(tmp_path):
    """Companion to the rejection tests above: an empty (or missing)
    decisions folder has nothing to break, so the change must still go
    through."""
    tmp_path = _init_repo(tmp_path)

    result = config.run(["--path", str(tmp_path), "--statusnew", "Draft"])

    assert result["updated_fields"] == ["statusnew"]


def test_config_does_not_commit_folderadr_if_the_new_folder_cannot_be_created(tmp_path, monkeypatch):
    """The new folder is created BEFORE the
    config write commits -- a failure creating it aborts cleanly with
    folderadr still pointing at the OLD, still-real directory, instead of
    committing the change first and leaving the repository pointing at a
    directory that doesn't exist."""
    tmp_path = _init_repo(tmp_path)

    from pathlib import Path as PathType

    real_mkdir = PathType.mkdir

    def failing_mkdir(self, *args, **kwargs):
        if self.name == "newfolder":
            raise PermissionError("Access is denied (simulated)")
        return real_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(PathType, "mkdir", failing_mkdir)

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--folderadr", "newfolder"])

    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.folderadr == "doc/adr"  # unchanged -- nothing committed
    assert not (tmp_path / "newfolder").exists()


def test_config_omitted_fields_keep_current_value(tmp_path):
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    config.run(["--path", str(tmp_path), "--headertitlefile", "Title"])

    after = load_repo_config(tmp_path / ".adrpy.json")
    assert after.prefix == "DOC"  # set earlier, preserved by the second call
    assert after.headertitlefile == "Title"


def test_config_rejects_non_integer_lenseq(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "three"])

    assert excinfo.value.code == "field-not-an-integer"


def test_config_still_enforces_schema_bounds(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "99"])

    assert excinfo.value.code == "config-lenseq-too-large"


def test_config_rejects_invalid_merged_value_leaves_file_untouched(tmp_path):
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / ".adrpy.json").read_text(encoding="utf-8")

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--separator", "~"])

    assert (tmp_path / ".adrpy.json").read_text(encoding="utf-8") == before


def test_config_rejects_folderadr_that_escapes_the_repository(tmp_path):
    """'../../evil' escapes the repository: `config` once wrote it straight
    to disk, silently bricking the repository until someone hand-edited
    the file back. The schema itself refuses it, before anything is
    written."""
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / ".adrpy.json").read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "../../evil"])

    assert excinfo.value.code == "config-folderadr-not-relative"
    assert (tmp_path / ".adrpy.json").read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "folderadr",
    [
        ".",
        pytest.param(
            "   ",
            marks=pytest.mark.skipif(
                sys.platform != "win32",
                reason="a whitespace-only path component only collapses away on Windows -- on "
                "POSIX it resolves to a literally-named '   ' entry instead, a different (and "
                "milder) case",
            ),
        ),
    ],
)
def test_config_rejects_folderadr_that_collapses_onto_the_repository_root(tmp_path, folderadr):
    """Unlike '../../evil' above (which escapes outward), '.' and (on
    Windows) a whitespace-only value silently resolve BACK to the
    repository root -- resolve_within must not accept that as 'not
    outside,' or folderadr would become indistinguishable from the repo
    root and every subsequent write would land next to
    .adrpy.json itself.

    ADR0007V01: '.' fails EARLIER, via a different, also-correct code --
    folderadr='.' has zero path components, which is a prefix of ANY
    folderlog value by construction, so the schema-level
    folderadr/folderlog containment guard (config-folderadr-folderlog-
    overlap) fires before resolve_within's own path-outside-repository
    check ever runs. The whitespace-only case has one (non-empty) path
    component, so it does not trip the containment guard and still
    surfaces via path-outside-repository."""
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / ".adrpy.json").read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", folderadr])

    expected_code = "config-folderadr-folderlog-overlap" if folderadr == "." else "path-outside-repository"
    assert excinfo.value.code == expected_code
    assert (tmp_path / ".adrpy.json").read_text(encoding="utf-8") == before


def test_config_rejects_a_whitespace_only_header_field_end_to_end(tmp_path):
    """The 16 header/status fields' blank rejection (tested at the schema
    layer in test_config.py) through the CLI command layer: config.run()
    propagates field-is-blank as config-field-is-blank, not some other
    wrapping."""
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--headerdisclaimer", "   "])

    assert excinfo.value.code == "config-field-is-blank"


def test_config_with_no_field_flags_reads_the_current_config_without_writing(tmp_path):
    """`config --path X` with no field flags must not rewrite (and
    reformat) the file as a side effect of a call that looks read-only --
    an agent needs a way to read the current config through the JSON
    contract (e.g. whether lenrevision > 0 before calling revise, or the
    current migrationpattern before calling migrate) without triggering
    a write."""
    tmp_path = _init_repo(tmp_path)
    before_bytes = (tmp_path / ".adrpy.json").read_bytes()

    result = config.run(["--path", str(tmp_path)])

    assert result["updated_fields"] == []
    assert result["config"]["prefix"] == "ADR"
    assert result["config"]["lenrevision"] == 0
    assert "activeplugins" not in result["config"]
    assert (tmp_path / ".adrpy.json").read_bytes() == before_bytes


def test_config_does_not_expose_activeplugins(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(UsageError):
        config.run(["--path", str(tmp_path), "--activeplugins", "Foo"])


def test_config_does_not_expose_language(tmp_path):
    """--language is a bootstrapping-only convenience (init, installconfig)
    -- an existing repository already has concrete label/template values on
    disk, so `config` has no equivalent shortcut to re-apply a language
    pack over them."""
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(UsageError):
        config.run(["--path", str(tmp_path), "--language", "pt-br"])


def test_config_target_directory_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path / "missing"), "--prefix", "X"])

    assert excinfo.value.code == "target-directory-not-found"


def test_config_not_found(tmp_path):
    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "X"])

    assert excinfo.value.code == "config-not-found"


def test_config_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path = _init_repo(tmp_path)

    assert main(["config", "--path", str(tmp_path), "--prefix", "DOC"]) == EXIT_SUCCESS


def test_config_describe_declares_correct_field_types():
    """describe() declares each field's real type: an integer field
    declared "string" is indistinguishable from a real string field until
    an agent hits field-not-an-integer by trial and error."""
    arguments = {argument["name"]: argument for argument in config.describe()["arguments"]}

    assert arguments["lenseq"]["type"] == "integer"
    assert arguments["lenversion"]["type"] == "integer"
    assert arguments["lenrevision"]["type"] == "integer"
    assert arguments["prefix"]["type"] == "string"


def test_config_describe_documents_the_real_domain_constraints():
    """A field's description states its real domain (separator ∈ {-,_,.},
    lenseq ∈ [3,6], prefix max 5 ASCII letters, ...), citing the same
    constants the validator itself enforces, so the two can never drift
    apart silently -- a tautological "New value for '<field>'." left an
    agent to discover it by deliberately triggering the corresponding
    config-*-invalid/-too-long error."""
    from adrpy.core import config as config_schema

    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    for separator in config_schema.VALID_SEPARATORS:
        assert separator in arguments["separator"]
    for transform in config_schema.VALID_CASE_TRANSFORMS:
        assert transform in arguments["casetransform"]
    assert str(config_schema.LENSEQ_MIN) in arguments["lenseq"]
    assert str(config_schema.LENSEQ_MAX) in arguments["lenseq"]
    assert str(config_schema.LENVERSION_MIN) in arguments["lenversion"]
    assert str(config_schema.LENVERSION_MAX) in arguments["lenversion"]
    assert str(config_schema.LENREVISION_MIN) in arguments["lenrevision"]
    assert str(config_schema.LENREVISION_MAX) in arguments["lenrevision"]
    assert str(config_schema.PREFIX_MAX_LENGTH) in arguments["prefix"]
    assert str(config_schema.FOLDERADR_MAX_LENGTH) in arguments["folderadr"]
    assert str(config_schema.HEADER_DISCLAIMER_MAX_LENGTH) in arguments["headerdisclaimer"]
    for field in config_schema._HEADER_LABEL_FIELDS_MAX_40:
        assert str(config_schema.HEADER_LABEL_MAX_LENGTH) in arguments[field]
    for field in config_schema._STATUS_LABEL_FIELDS:
        assert str(config_schema.STATUS_LABEL_MAX_LENGTH) in arguments[field]
    assert "N" in arguments["migrationpattern"] and "T" in arguments["migrationpattern"]


def test_config_describe_does_not_falsely_claim_these_two_fields_are_settable_to_empty():
    """parse_flags structurally rejects an empty optional value before it
    ever reaches the field, so this command can never set template or
    prefix to empty (only `init --seed` can): their descriptions must not
    claim "may be empty" without qualifying it. migrationpattern is the
    exception: config accepts an empty value to clear it, and its
    description says so."""
    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    for field in ("template", "prefix"):
        assert "can't set it to an empty string here" in arguments[field]
        assert "init --seed" in arguments[field]
    assert "clears it" in arguments["migrationpattern"]
    assert "status-or-separator-change-blocked-by-existing-decisions" in arguments["migrationpattern"]


def test_config_describe_documents_the_forbidden_character_constraint():
    """These 16 fields all go through reject_embedded_delimiter on top of
    their length bound, so their descriptions say so -- an agent following
    only the stated domain (any string <= max length, non-empty) would
    otherwise hit config-field-contains-forbidden-character with no prior
    warning."""
    from adrpy.core import config as config_schema

    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    forbidden_char_fields = config_schema._HEADER_LABEL_FIELDS_MAX_40 + config_schema._STATUS_LABEL_FIELDS + (
        "headerdisclaimer",
    )
    for field in forbidden_char_fields:
        assert "line-break-like character" in arguments[field]


def test_config_describe_documents_the_asymmetric_read_write_json_shape():
    """A read result has a `config` key; a write result never does (only
    `updated_fields`) -- a generic wrapper that reads `data.config`
    unconditionally after any `config` call would KeyError on a write."""
    assert "`config` key" in config.describe()["description"]


def test_field_description_fails_loudly_for_a_field_it_does_not_recognize():
    """_field_description fails loudly for a field none of its branches
    recognize, instead of returning a generic "New value for '<field>'." --
    a tautological description an agent can't learn anything from, which
    would otherwise ship silently the moment a new field is added to
    _EDITABLE_FIELDS without a matching branch."""
    from adrpy.cli.config import _field_description

    with pytest.raises(AssertionError, match="no-such-field"):
        _field_description("no-such-field")


def test_config_refuses_a_prefix_change_while_a_decision_is_recognized(tmp_path):
    # The prefix is part of every current-scheme name: changing it would
    # make every existing decision unrecognized.
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Keep me"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "DEC"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["prefix"], "existing_decisions": 1}
    assert load_repo_config(tmp_path / ".adrpy.json").prefix == "ADR"


def test_config_refuses_a_prefix_change_that_would_adopt_an_unrelated_file(tmp_path):
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    (adr_dir / "XYZ001V01-x.md").write_bytes(b"hand written, not a real decision file\n")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "XYZ"])

    assert excinfo.value.code == "prefix-change-would-adopt-unrelated-files"
    assert [os.path.basename(path) for path in excinfo.value.data["adopted_files"]] == ["XYZ001V01-x.md"]
    assert load_repo_config(tmp_path / ".adrpy.json").prefix == "ADR"


def test_config_refuses_a_prefix_and_separator_change_that_adopts_only_together(tmp_path):
    # Neither field alone makes this file an ADR name; both together do.
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    (adr_dir / "XYZ0001V01_foo.md").write_bytes(b"hand written, not a real decision file\n")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "XYZ", "--separator", "_"])

    assert excinfo.value.code in (
        "prefix-change-would-adopt-unrelated-files",
        "separator-change-would-adopt-unrelated-files",
    )
    assert [os.path.basename(path) for path in excinfo.value.data["adopted_files"]] == ["XYZ0001V01_foo.md"]
    assert load_repo_config(tmp_path / ".adrpy.json").prefix == "ADR"


def test_config_allows_a_prefix_change_on_an_empty_repository(tmp_path):
    tmp_path = _init_repo(tmp_path)

    result = config.run(["--path", str(tmp_path), "--prefix", "DEC"])

    assert result["updated_fields"] == ["prefix"]
    assert load_repo_config(tmp_path / ".adrpy.json").prefix == "DEC"


def test_a_refused_config_does_not_recreate_a_missing_folderadr(tmp_path):
    import shutil

    tmp_path = _init_repo(tmp_path)
    shutil.rmtree(tmp_path / "doc" / "adr")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--lenseq", "abc"])

    assert excinfo.value.code == "field-not-an-integer"
    assert not (tmp_path / "doc" / "adr").exists()


def test_a_guard_refusal_does_not_leave_behind_the_folderadr_it_created_to_scan(tmp_path):
    import shutil

    from adrpy.cli import log

    tmp_path = _init_repo(tmp_path)
    log.run(
        [
            "--path", str(tmp_path), "--classification", "scope-note", "--scope", "lock",
            "--slug", "a-note", "--summary", "A note", "--body", "Body.",
        ]
    )
    shutil.rmtree(tmp_path / "doc" / "adr")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderlog", "doc/elsewhere"])

    assert excinfo.value.code == "folderlog-change-blocked-by-existing-entries"
    assert not (tmp_path / "doc" / "adr").exists()


class _Crash(BaseException):
    """Anything that is not a CommandError (not KeyboardInterrupt, which
    would stop the whole test session if it escaped)."""


@pytest.mark.parametrize("existing", [None, "a"])
def test_a_refused_config_removes_every_folder_it_created_and_none_that_existed(tmp_path, existing):
    import shutil

    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--folderadr", "a/b/c"])
    shutil.rmtree(tmp_path / "a")
    if existing:
        (tmp_path / existing).mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (other / "ADR001V01-junk.md").write_text("junk\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "other"])

    assert excinfo.value.code == "folderadr-change-would-adopt-unrelated-files"
    assert (tmp_path / "a").exists() == bool(existing)
    assert not (tmp_path / "a" / "b").exists()


def test_any_failure_of_the_guard_removes_the_folder_it_created(tmp_path, monkeypatch):
    import shutil

    tmp_path = _init_repo(tmp_path)
    shutil.rmtree(tmp_path / "doc")

    def crashing_guard(*_args, **_kwargs):
        raise _Crash()

    monkeypatch.setattr(config, "validate_config_change", crashing_guard)

    with pytest.raises(_Crash):
        config.run(["--path", str(tmp_path), "--separator", "_"])

    assert not (tmp_path / "doc").exists()


def test_a_refusal_keeps_a_created_folder_that_received_content(tmp_path, monkeypatch):
    import shutil

    tmp_path = _init_repo(tmp_path)
    shutil.rmtree(tmp_path / "doc" / "adr")

    def guard_while_someone_writes(*_args, **_kwargs):
        (tmp_path / "doc" / "adr" / "notes.txt").write_text("someone else's\n", encoding="utf-8")
        raise CommandError("status-or-separator-change-blocked-by-existing-decisions", "refused")

    monkeypatch.setattr(config, "validate_config_change", guard_while_someone_writes)

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--separator", "_"])

    assert (tmp_path / "doc" / "adr" / "notes.txt").exists()


@pytest.mark.parametrize("new_pattern", ["N00:04T05", ""])
def test_a_wrong_migrationpattern_can_be_fixed_while_no_legacy_decision_is_migrated(tmp_path, new_pattern):
    # Owner decision: only a LEGACY decision that already has a header
    # (migrated) blocks a migrationpattern change. Hand-written files the
    # pattern merely matches by name are not decisions yet: fixing (or
    # clearing) a wrong pattern before migrate must be possible.
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    adr_dir = tmp_path / "doc" / "adr"
    (adr_dir / "0001-use-postgres.md").write_bytes(b"# Use Postgres\n")
    (adr_dir / "0002-use-rest.md").write_bytes(b"# Use REST\n")

    result = config.run(["--path", str(tmp_path), "--migrationpattern", new_pattern])

    assert result["updated_fields"] == ["migrationpattern"]
    assert config.run(["--path", str(tmp_path)])["config"]["migrationpattern"] == new_pattern


@pytest.mark.parametrize("new_pattern", ["N00:04T05", ""])
def test_a_migrated_legacy_decision_still_blocks_a_migrationpattern_change(tmp_path, new_pattern):
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0001-use-postgres.md")
    (tmp_path / "doc" / "adr" / "0002-use-rest.md").write_bytes(b"# Use REST\n")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--migrationpattern", new_pattern])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["migrationpattern"], "existing_decisions": 1}


def _legacy_names(tmp_path):
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    for name in ("0001-use-postgres.md", "0002-use-rest.md", "2024-roadmap.md"):
        (adr_dir / name).write_bytes(b"# x\n")
    return adr_dir


def test_setting_migrationpattern_previews_what_it_recognizes_and_flags_a_likely_wrong_pattern(tmp_path):
    tmp_path = _init_repo(tmp_path)
    adr_dir = _legacy_names(tmp_path)

    result = config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])

    assert result["migrationpattern_preview"] == [
        {"file": str(adr_dir / "0001-use-postgres.md"), "number": 1, "version": 0, "title": "-use-postgres"},
        {"file": str(adr_dir / "0002-use-rest.md"), "number": 2, "version": 0, "title": "-use-rest"},
        {"file": str(adr_dir / "2024-roadmap.md"), "number": 2024, "version": 0, "title": "-roadmap"},
    ]
    assert any("start with a separator" in w and "T05" in w for w in result["warnings"])
    assert any("2024" in w and "far above" in w and "not a decision" in w for w in result["warnings"])


def test_a_right_migrationpattern_previews_without_warnings(tmp_path):
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    (adr_dir / "0001-use-postgres.md").write_bytes(b"# x\n")

    result = config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T05"])

    assert [entry["title"] for entry in result["migrationpattern_preview"]] == ["use-postgres"]
    assert result["warnings"] == []


def test_migrationpattern_help_explains_the_syntax_and_points_at_the_explore_preview():
    info = config.describe()
    argument = next(a for a in info["arguments"] if a["name"] == "migrationpattern")

    assert "'N00:04T05'" in argument["description"] and "`0001-title.md`" in argument["description"]
    assert "adrpy explore --path ." in info["description"]


def test_an_interrupt_while_previewing_a_migrationpattern_leaves_the_config_unchanged(tmp_path, monkeypatch):
    # The preview is computed before the write: nothing that can fail
    # runs after the config is on disk.
    _init_repo(tmp_path)
    (tmp_path / "doc" / "adr" / "0001-use-x.md").write_text("# x\n", encoding="utf-8")
    before = (tmp_path / ".adrpy.json").read_bytes()
    real_scan = config.scan_tree
    calls = {"n": 0}

    def interrupted_on_the_second_scan(folder):
        calls["n"] += 1
        if calls["n"] == 2:
            raise KeyboardInterrupt()
        return real_scan(folder)

    monkeypatch.setattr(config, "scan_tree", interrupted_on_the_second_scan)

    with pytest.raises(KeyboardInterrupt):
        config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T05"])

    assert (tmp_path / ".adrpy.json").read_bytes() == before


def test_a_folder_that_cannot_be_created_leaves_none_of_its_new_parents(tmp_path, monkeypatch):
    _init_repo(tmp_path)
    real_mkdir = os.mkdir

    def leaf_denied(path, *args, **kwargs):
        # Denied only once its parents exist, as with an ACL on `a`.
        if os.path.basename(os.fspath(path)) == "b" and os.path.isdir(os.path.dirname(os.fspath(path))):
            raise PermissionError(13, "Permission denied", os.fspath(path))
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", leaf_denied)

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--folderadr", "zz/a/b"])

    assert not (tmp_path / "zz").exists()



def test_a_header_label_change_is_blocked_by_existing_decisions(tmp_path):
    """The fields row is recognized by the configured label: changing it
    with decisions in place would make every header unreadable."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--headertablefields", "Campos"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data["changed_fields"] == ["headertablefields"]


def test_a_header_label_change_is_allowed_before_any_decision(tmp_path):
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--headertablefields", "Campos"])
    assert "Campos" in (tmp_path / ".adrpy.json").read_text(encoding="utf-8")



def _with_retired_fields(tmp_path):
    import json

    config_path = tmp_path / ".adrpy.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data.update({"activeplugins": [], "disableplugins": False})
    config_path.write_text(json.dumps(data), encoding="utf-8")
    return config_path


def test_a_config_with_the_retired_plugin_fields_is_read_with_a_warning(tmp_path, capsys):
    """activeplugins and disableplugins are no longer config fields: a
    config that still holds them is read, and the answer says they were
    ignored."""
    import json

    from adrpy.__main__ import main

    tmp_path = _init_repo(tmp_path)
    _with_retired_fields(tmp_path)

    assert main(["config", "--path", str(tmp_path)]) == 0
    answer = json.loads(capsys.readouterr().out)
    assert answer["success"]
    assert "activeplugins" not in answer["data"]["config"]
    assert any("activeplugins" in warning and "disableplugins" in warning for warning in answer["data"]["warnings"])


@pytest.mark.parametrize("raised, code", [(OSError(5, "denied"), "io-error"), (ValueError("x"), "internal-error"),
                                          (KeyboardInterrupt(), "interrupted")])
def test_the_retired_field_warning_reaches_every_failure(tmp_path, capsys, monkeypatch, raised, code):
    """The config-read warning is part of the answer whatever way the
    command then fails, not only on a CommandError."""
    import json

    from adrpy import __main__ as entry

    tmp_path = _init_repo(tmp_path)
    _with_retired_fields(tmp_path)
    real_run = config.run

    def failing(args):
        real_run(["--path", str(tmp_path)])
        raise raised

    monkeypatch.setattr(config, "run", failing)
    entry.main(["config", "--path", str(tmp_path)])
    answer = json.loads(capsys.readouterr().out)

    assert answer["code"] == code
    assert any("activeplugins" in warning for warning in answer.get("warnings", []))


def test_the_retired_field_warning_names_the_writes_that_remove_them(tmp_path, capsys):
    """Only config and installconfig rewrite a config file: the warning must
    not promise that any write does."""
    import json

    from adrpy.__main__ import main

    tmp_path = _init_repo(tmp_path)
    _with_retired_fields(tmp_path)
    main(["config", "--path", str(tmp_path)])
    [warning] = [w for w in json.loads(capsys.readouterr().out)["data"]["warnings"] if "activeplugins" in w]

    assert "removed at the next write" not in warning
    assert "adrpy config" in warning


def test_a_write_drops_the_retired_plugin_fields(tmp_path):
    tmp_path = _init_repo(tmp_path)
    config_path = _with_retired_fields(tmp_path)

    config.run(["--path", str(tmp_path), "--headerscope", "Escopo"])

    text = config_path.read_text(encoding="utf-8")
    assert "activeplugins" not in text and "disableplugins" not in text


def test_another_unknown_field_is_still_an_error(tmp_path):
    import json

    tmp_path = _init_repo(tmp_path)
    config_path = tmp_path / ".adrpy.json"
    data = json.loads(config_path.read_text(encoding="utf-8"))
    data["somethingelse"] = 1
    config_path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path)])

    assert excinfo.value.code == "config-unexpected-field"


@pytest.mark.parametrize("flag", ["--disableplugins", "--activeplugins"])
def test_the_plugin_flags_are_gone(tmp_path, flag):
    tmp_path = _init_repo(tmp_path)
    with pytest.raises(UsageError):
        config.run(["--path", str(tmp_path), flag, "true"])
