import json
import os
import sys
import threading

from adrpy.cli import config, init, new
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError, UsageError

import pytest


def _init_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    return tmp_path


def _write_legacy_file(tmp_path, filename, content="Legacy content\n"):
    # Raw bytes, not new.run -- legacy-scheme files predate the tool and
    # are never created by it; mirrors test_migrate.py's own helper.
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / filename).write_bytes(content.encode("utf-8"))
    return adr_dir / filename


def test_config_aborts_if_folderadr_changed_after_lock_acquired(tmp_path, monkeypatch):
    """Config's own comment claimed `current`
    (fresh, inside the lock) and `folder` (this same lock's own
    location) "both are the pre-edit state" -- that invariant didn't
    actually hold. If a concurrent process changes folderadr between
    this call's own bootstrap read (which decides the lock's location)
    and the moment it acquires the lock, this call would lock, scan, and
    validate against a directory the repository no longer uses.
    Simulates the race by returning a stale config from the bootstrap
    read while the file on disk already has the new value."""
    tmp_path = _init_repo(tmp_path)
    stale_bootstrap = load_repo_config(tmp_path / "adr-config.adrplus")

    monkeypatch.setattr(
        config,
        "resolve_target_and_config",
        lambda path: (tmp_path, tmp_path / "adr-config.adrplus", stale_bootstrap),
    )

    data = json.loads((tmp_path / "adr-config.adrplus").read_text(encoding="utf-8"))
    data["folderadr"] = "doc/adrB"
    (tmp_path / "adr-config.adrplus").write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--prefix", "XYZ"])

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert excinfo.value.data == {"locked_folderadr": "doc/adr", "current_folderadr": "doc/adrB"}


def test_config_updates_a_single_field_and_preserves_the_rest(tmp_path):
    tmp_path = _init_repo(tmp_path)
    before = load_repo_config(tmp_path / "adr-config.adrplus")

    result = config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    assert result["updated_fields"] == ["prefix"]
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.prefix == "DOC"
    assert after.folderadr == before.folderadr
    assert after.lenseq == before.lenseq
    assert after.activeplugins == before.activeplugins  # untouched, not exposed


def test_config_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage."""
    tmp_path = _init_repo(tmp_path)
    real_atomic_write_text = config.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(config, "atomic_write_text", flaky_atomic_write_text)

    result = config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    assert any("3 attempts" in w for w in result["warnings"])


def test_concurrent_config_calls_on_different_fields_do_not_lose_an_update(tmp_path, monkeypatch):
    """Two concurrent calls editing DIFFERENT fields with no lock at all
    would silently lose one of the two edits, contradicting this
    command's own documented contract ("an omitted flag preserves the
    repo's current value, never resets it"). The same repository lock
    the other 8 write commands already use (scoped to folderadr) closes
    this: the second caller simply waits, then reads fresh once it
    acquires the lock, so BOTH edits survive instead of either being
    lost or the second one failing outright."""
    tmp_path = _init_repo(tmp_path)

    from adrpy.cli import config as config_module

    # Widens the read-merge-validate window so both calls are genuinely
    # in flight at once -- with a real lock in place, correctness no
    # longer depends on the exact interleaving (unlike the lock-less
    # code this replaces), so a plain delay (not event-based
    # choreography) is enough here.
    real_parse_repo_config = config_module.parse_repo_config

    def delayed_parse_repo_config(*args, **kwargs):
        import time

        time.sleep(0.05)
        return real_parse_repo_config(*args, **kwargs)

    monkeypatch.setattr(config_module, "parse_repo_config", delayed_parse_repo_config)

    results = [None, None]
    errors = [None, None]
    barrier = threading.Barrier(2)

    def call(index, args):
        barrier.wait()
        try:
            results[index] = config.run(args)
        except Exception as error:  # noqa: BLE001 -- captured for the assertion, not swallowed
            errors[index] = error

    threads = [
        threading.Thread(target=call, args=(0, ["--path", str(tmp_path), "--prefix", "XYZ"])),
        threading.Thread(target=call, args=(1, ["--path", str(tmp_path), "--lenseq", "5"])),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == [None, None], f"expected both calls to succeed, got errors: {errors}"
    assert results[0]["updated_fields"] == ["prefix"]
    assert results[1]["updated_fields"] == ["lenseq"]

    final = load_repo_config(tmp_path / "adr-config.adrplus")
    assert final.prefix == "XYZ"
    assert final.lenseq == 5


def test_config_creates_the_decisions_folder_if_missing_before_locking(tmp_path):
    """The repository lock this command now acquires lives inside
    folderadr -- unlike the other 8 write commands, which only ever run
    after `init` already created that directory, nothing requires it to
    exist before `config` runs (e.g. it was deleted, or folderadr was
    just repointed at a fresh path). core.lock._try_create only handles
    FileExistsError, not a FileNotFoundError from a missing parent --
    ensures the directory exists first, matching init's own precedent
    for this identical situation."""
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
    after = load_repo_config(tmp_path / "adr-config.adrplus")
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
    before = load_repo_config(tmp_path / "adr-config.adrplus")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert excinfo.value.code == "folderadr-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"folderadr": "doc/adr", "existing_decisions": 1}
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.folderadr == before.folderadr  # nothing was written


def test_config_folderadr_change_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Folderadr-change-scan-
    incomplete (reject_folderadr_change_if_decisions_exist's own fail-
    closed path) was only ever tested at the core/lifecycle level, never
    through this real CLI command."""
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    blocked = adr_dir / "restricted"
    blocked.mkdir()
    before = load_repo_config(tmp_path / "adr-config.adrplus")

    real_scandir = os.scandir

    def flaky_scandir(path="."):
        if os.path.abspath(path) == os.path.abspath(blocked):
            raise PermissionError(13, "Access is denied", str(blocked))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", flaky_scandir)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert excinfo.value.code == "folderadr-change-scan-incomplete"
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.folderadr == before.folderadr  # nothing was written


def test_config_allows_a_folderadr_change_when_no_decisions_exist_yet(tmp_path):
    """Companion to the rejection test above: an empty (or missing)
    decisions folder is exactly the case ADR001's own exemption for init
    already covers -- nothing to orphan, so the change must still go
    through, and the new folder must exist afterward for the next
    command to lock."""
    tmp_path = _init_repo(tmp_path)

    result = config.run(["--path", str(tmp_path), "--folderadr", "decisions"])

    assert result["updated_fields"] == ["folderadr"]
    assert (tmp_path / "decisions").is_dir()


def test_config_rejects_a_status_label_change_when_decisions_already_exist(tmp_path):
    """ADR004V01: a status label change on a repository that already has
    recognized decisions can break a marker-less status cell's text
    match -- same shape guard as folderadr's own, confirmed live before
    this existed (changing --statusnew made an existing decision
    is_valid: false)."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    before = load_repo_config(tmp_path / "adr-config.adrplus")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statusnew", "Draft"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["statusnew"], "existing_decisions": 1}
    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.statusnew == before.statusnew  # nothing was written


def test_config_rejects_a_separator_change_when_decisions_already_exist(tmp_path):
    """ADR004V01: a separator change on a repository that already has
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
    """ADR004V02: the guard's blanket check (separator, among others) and
    its legacy-scoped check (migrationpattern) must be evaluated
    independently, not short-circuited against each other -- a round-20
    test-adequacy pass found that mutating the two checks into an
    if/elif chain (so the legacy check is skipped once the blanket
    check already matched) left the full suite green, since no existing
    test combined a mixed-scheme repository with changing both fields
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
    """Same as the statusrej test above, for statussup -- closes the
    guard's field coverage for all 4 status labels."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statussup", "Replaced"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["statussup"], "existing_decisions": 1}


def test_config_reports_the_correct_count_with_more_than_one_existing_decision(tmp_path):
    """Every prior guard test creates exactly one decision, so
    `existing_decisions` was never proven to be a real count rather than
    a hardcoded 1."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    new.run(["--path", str(tmp_path), "--title", "Second decision"])
    new.run(["--path", str(tmp_path), "--title", "Third decision"])

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--statusnew", "Draft"])

    assert excinfo.value.data == {"changed_fields": ["statusnew"], "existing_decisions": 3}


def test_config_migrationpattern_only_block_counts_only_legacy_scheme_decisions(tmp_path):
    """A round-20 test-adequacy pass found the prior version of this
    count test used a scheme-homogeneous fixture (all current-scheme),
    so it could not distinguish 'a real total count' from 'a real count
    scoped to the right scheme' -- a scheme-miscounting regression would
    have slipped through undetected. This test uses a MIXED-scheme
    repository and changes ONLY migrationpattern, so the count must
    reflect just the legacy-scheme subset (1), never the total (2)."""
    tmp_path = _init_repo(tmp_path)
    new.run(["--path", str(tmp_path), "--title", "Current scheme decision"])
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0002T02.md")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--migrationpattern", "N00:05T05"])

    assert excinfo.value.data == {"changed_fields": ["migrationpattern"], "existing_decisions": 1}


def test_config_allows_a_migrationpattern_change_when_only_current_scheme_decisions_exist(tmp_path):
    """ADR004V02: migrationpattern is only ever read by naming.py's
    parse_legacy_filename -- a repository with only current-scheme
    decisions has nothing that a migrationpattern change could break.
    This was ADR004V01's own gap: a blanket guard would have refused
    this harmless change for no reason (confirmed via mutation before
    the fix -- see the audit finding this test closes)."""
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


def test_config_rejects_a_separator_change_when_only_legacy_scheme_decisions_exist(tmp_path):
    """ADR004V02 (corrected): separator is only ever READ by naming.py's
    parse_filename (the current scheme), but that is not enough to scope
    the guard to current-scheme decisions only -- parse_any_filename
    tries the current scheme FIRST, so a separator value that happens to
    already appear in a legacy filename can make it newly match under
    parse_filename, silently reclassifying a legacy decision as
    current-scheme with a different number/title. A round-20 audit
    found this live (a scoped version of this guard incorrectly allowed
    this exact scenario, and the file's own scheme flipped on the next
    scan) -- separator is blanket again as a result; only
    migrationpattern is genuinely safe to scope (naming.py's
    parse_filename never reads it, so it has no mirror reclassification
    risk)."""
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0001T01.md")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--separator", "_"])

    assert excinfo.value.code == "status-or-separator-change-blocked-by-existing-decisions"
    assert excinfo.value.data == {"changed_fields": ["separator"], "existing_decisions": 1}


def test_config_separator_change_does_not_silently_reclassify_a_legacy_file_as_current_scheme(tmp_path):
    """Direct regression test for the round-20 finding itself, not just
    the guard's own refusal: even bypassing the guard's own check (by
    changing a field the guard does NOT protect against this exact
    risk) would be dangerous -- this test locks in that the guard DOES
    block the one live reproduction that exposed the bug, end to end
    through explore, not just via the raised error code."""
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])
    _write_legacy_file(tmp_path, "0001_MyTitle.md")

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--separator", "_"])

    # Nothing committed -- the file is still recognized under its
    # original scheme/identity, not silently reclassified.
    config_after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert config_after.separator == "-"


def test_config_rejects_a_separator_change_that_would_adopt_an_unrelated_unrecognized_file(tmp_path):
    """A deferred finding (found by a post-round-20 verification pass,
    confirmed live, then fixed): every check above is keyed on
    decisions already recognized under the OLD config -- none of them
    catch a file that ISN'T currently recognized by any scheme becoming
    newly recognized. An unrelated hand-written .md file (never created
    via `new`, no relationship to the decision lifecycle) sitting in the
    decisions folder must never be silently adopted as a genuine
    decision just because a separator change happens to make its own
    name parse."""
    tmp_path = _init_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    (adr_dir / "0001_MyTitle.md").write_bytes(b"hand written, not a real decision file\n")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--separator", "_"])

    assert excinfo.value.code == "separator-change-would-adopt-unrelated-files"
    assert len(excinfo.value.data["adopted_files"]) == 1
    assert "0001_MyTitle.md" in excinfo.value.data["adopted_files"][0]
    # Nothing committed.
    config_after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert config_after.separator == "-"


def test_config_allows_a_separator_change_that_adopts_nothing(tmp_path, monkeypatch):
    """Companion to the rejection test above: a separator change with no
    unrelated file anywhere that would newly parse under the new value
    must still go through -- this guard must not become a blanket
    refusal to ever change separator at all.

    A round-21 test-adequacy pass found the original, plain version of
    this test (an empty decisions folder, asserting only the call
    succeeds) could not distinguish "the adoption scan ran and
    correctly found nothing new" from "the adoption scan never ran at
    all" -- mutation-confirmed: disabling the check entirely still left
    that version green, since an empty folder has nothing to adopt
    either way. A file guaranteed to stay unrecognized under both
    separators has the exact same problem for the same reason. Proven
    instead via a call-count spy on scan_decisions -- the guard scans
    twice for a successful separator change (once for `existing` under
    old_config, once for the adoption check under the separator-only
    config); a disabled adoption check would only scan once."""
    tmp_path = _init_repo(tmp_path)
    from adrpy.core import lifecycle as lifecycle_module

    real_scan_decisions = lifecycle_module.scan_decisions
    calls = []

    def counting_scan_decisions(*args, **kwargs):
        calls.append((args, kwargs))
        return real_scan_decisions(*args, **kwargs)

    monkeypatch.setattr(lifecycle_module, "scan_decisions", counting_scan_decisions)

    result = config.run(["--path", str(tmp_path), "--separator", "_"])

    assert result["updated_fields"] == ["separator"]
    assert len(calls) == 2  # existing (old_config) + the adoption check (separator-only config)


def test_config_separator_and_migrationpattern_change_together_does_not_cross_attribute_adoption(tmp_path):
    """A round-21 stability finding, confirmed live and fixed: the
    adoption check used to scan with the FULL new config, so a call
    changing both --separator and --migrationpattern at once could get
    wrongly refused over files only migrationpattern's own (intentional)
    adoption would newly recognize -- blaming separator for something
    it had no part in. This file's own name contains no "_" anywhere,
    so separator alone provably adopts nothing; only migrationpattern
    does, which must not trigger the separator-only adoption check."""
    tmp_path = _init_repo(tmp_path)
    _write_legacy_file(tmp_path, "0001UsePostgreSQL.md")

    result = config.run(["--path", str(tmp_path), "--separator", "_", "--migrationpattern", "N00:04T04"])

    assert set(result["updated_fields"]) == {"separator", "migrationpattern"}


def test_config_blocking_fields_check_wins_over_the_adoption_check_when_both_could_apply(tmp_path):
    """A round-21 test-adequacy finding: the adoption check is only ever
    reached once the blocking-fields check above it has already passed
    -- pins this precedence explicitly, since nothing did before. An
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
    """The new adoption guard is deliberately scoped to `separator`
    only -- migrationpattern recognizing a previously-unrecognized
    legacy file is that field's own documented, intentional purpose
    (ADR002V01), not the bug this guard exists to close. A
    migrationpattern change that newly recognizes an existing
    hand-written file (with no other guarded field changing, and no
    already-recognized decision at risk) must still succeed."""
    tmp_path = _init_repo(tmp_path)
    _write_legacy_file(tmp_path, "0001T01.md")  # unrecognized: no migrationpattern configured yet

    result = config.run(["--path", str(tmp_path), "--migrationpattern", "N00:04T04"])

    assert result["updated_fields"] == ["migrationpattern"]


def test_config_status_or_separator_change_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Mirrors the folderadr guard's own equivalent test -- status-or-
    separator-change-scan-incomplete (the new guard's own fail-closed
    path) needs the same CLI-level coverage."""
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

    assert excinfo.value.code == "status-or-separator-change-scan-incomplete"


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

    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.folderadr == "doc/adr"  # unchanged -- nothing committed
    assert not (tmp_path / "newfolder").exists()


def test_config_omitted_fields_keep_current_value(tmp_path):
    tmp_path = _init_repo(tmp_path)
    config.run(["--path", str(tmp_path), "--prefix", "DOC"])

    config.run(["--path", str(tmp_path), "--headertitlefile", "Title"])

    after = load_repo_config(tmp_path / "adr-config.adrplus")
    assert after.prefix == "DOC"  # set earlier, preserved by the second call
    assert after.headertitlefile == "Title"


def test_config_toggles_disableplugins(tmp_path):
    tmp_path = _init_repo(tmp_path)

    config.run(["--path", str(tmp_path), "--disableplugins", "true"])
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is True

    config.run(["--path", str(tmp_path), "--disableplugins", "false"])
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is False


def test_config_rejects_invalid_disableplugins_value(tmp_path):
    tmp_path = _init_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--disableplugins", "maybe"])

    assert excinfo.value.code == "field-not-a-boolean"


@pytest.mark.parametrize("value", ["True", "TRUE", " true ", "False", " FALSE "])
def test_config_normalizes_non_canonical_disableplugins_input(tmp_path, value):
    """--disableplugins's own
    `.strip().lower()` normalization had no test with non-canonical input
    (only exactly "true"/"false"/"maybe")."""
    tmp_path = _init_repo(tmp_path)

    config.run(["--path", str(tmp_path), "--disableplugins", value])

    expected = value.strip().lower() == "true"
    assert load_repo_config(tmp_path / "adr-config.adrplus").disableplugins is expected


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
    before = (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8")

    with pytest.raises(CommandError):
        config.run(["--path", str(tmp_path), "--separator", "~"])

    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == before


def test_config_rejects_folderadr_that_escapes_the_repository(tmp_path):
    """'../../evil' passes the schema-level relative-
    path check (it has no drive/leading slash) but still escapes the
    repository once resolved -- unlike `init`, which validates this
    before writing, `config` wrote it straight to disk, silently
    bricking the repository (every subsequent command failed with
    path-outside-repository) until someone hand-edited the file back."""
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", "../../evil"])

    assert excinfo.value.code == "path-outside-repository"
    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == before


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
    adr-config.adrplus itself."""
    tmp_path = _init_repo(tmp_path)
    before = (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        config.run(["--path", str(tmp_path), "--folderadr", folderadr])

    assert excinfo.value.code == "path-outside-repository"
    assert (tmp_path / "adr-config.adrplus").read_text(encoding="utf-8") == before


def test_config_rejects_a_whitespace_only_header_field_end_to_end(tmp_path):
    """The 16 header/status fields' forbidden-character/blank rejection
    is thoroughly tested at the schema layer (test_config.py), but needs
    its own, independent coverage through the CLI command layer too --
    confirming config.run() actually propagates field-is-blank as
    config-field-is-blank, not some other wrapping."""
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
    before_bytes = (tmp_path / "adr-config.adrplus").read_bytes()

    result = config.run(["--path", str(tmp_path)])

    assert result["updated_fields"] == []
    assert result["config"]["prefix"] == "ADR"
    assert result["config"]["lenrevision"] == 0
    assert "activeplugins" not in result["config"]
    assert (tmp_path / "adr-config.adrplus").read_bytes() == before_bytes


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
    """Every editable field was declared "string" in
    describe(), including the 3 integer fields and the boolean --
    indistinguishable from a real string field until an agent hit
    field-not-an-integer/field-not-a-boolean by trial and error."""
    arguments = {argument["name"]: argument for argument in config.describe()["arguments"]}

    assert arguments["lenseq"]["type"] == "integer"
    assert arguments["lenversion"]["type"] == "integer"
    assert arguments["lenrevision"]["type"] == "integer"
    assert arguments["disableplugins"]["type"] == "boolean"
    assert arguments["prefix"]["type"] == "string"


def test_config_describe_documents_the_real_domain_constraints():
    """Every field's description was the tautological
    "New value for '<field>'." -- an agent could only discover a field's
    real domain (separator ∈ {-,_,.}, lenseq ∈ [3,6], prefix max 5
    ASCII letters, ...) by deliberately triggering the corresponding
    config-*-invalid/-too-long error. Descriptions now cite the same
    constants the validator itself enforces, so the two can never drift
    apart silently."""
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
    assert "true" in arguments["disableplugins"] and "false" in arguments["disableplugins"]


def test_config_describe_does_not_falsely_claim_these_three_fields_are_settable_to_empty():
    """_field_description advertised
    "may be empty" for migrationpattern/template/prefix, but every
    optional flag goes through parse_flags, which structurally rejects
    an empty string before it ever reaches the field -- this command can
    never actually set any of the three to empty (only `init --seed`
    can). The description must not claim otherwise without qualifying it."""
    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    for field in ("migrationpattern", "template", "prefix"):
        assert "can't set it to an empty string here" in arguments[field]
        assert "init --seed" in arguments[field]


def test_config_describe_documents_the_forbidden_character_constraint():
    """These 16 fields all go
    through reject_embedded_delimiter on top of their length bound, but
    none of their descriptions mentioned it -- an agent following only
    the stated domain (any string <= max length, non-empty) could still
    hit config-field-contains-forbidden-character with no prior warning."""
    from adrpy.core import config as config_schema

    arguments = {argument["name"]: argument["description"] for argument in config.describe()["arguments"]}

    forbidden_char_fields = config_schema._HEADER_LABEL_FIELDS_MAX_40 + config_schema._STATUS_LABEL_FIELDS + (
        "headerdisclaimer",
    )
    for field in forbidden_char_fields:
        assert "line-break-like character" in arguments[field]


def test_config_describe_documents_the_asymmetric_read_write_json_shape():
    """A read result has a `config`
    key; a write result never does (only `updated_fields`) -- a generic
    wrapper that reads `data.config` unconditionally after any `config`
    call would KeyError on a write. Undocumented before this."""
    assert "`config` key" in config.describe()["description"]


def test_field_description_fails_loudly_for_a_field_it_does_not_recognize():
    """_field_description's own
    fallback (`return f"New value for '{field}'."`) is unreachable today
    -- every one of the 26 fields in _EDITABLE_FIELDS hits a specific
    branch above it (confirmed by test_config_describe_documents_the_
    real_domain_constraints exercising every field). Silently returning
    that generic, uninformative string for a field none of the branches
    recognize would be the same usability regression M2 already fixed
    (a tautological description an agent can't learn anything from) --
    reintroduced silently the moment a new field is ever added to
    _EDITABLE_FIELDS without a matching branch here. Fails loudly
    instead, so that moment is caught immediately rather than shipped."""
    from adrpy.cli.config import _field_description

    with pytest.raises(AssertionError, match="no-such-field"):
        _field_description("no-such-field")
