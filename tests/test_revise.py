import json
import os
from datetime import date, timedelta

from adrpy.cli import approve, config, init, new, reject, revise
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header

import pytest

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"


def _config_with_revisions():
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["lenrevision"] = 2
    return data


def _setup_accepted_repo_with_revisions(tmp_path):
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_config_with_revisions()), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    new.run(
        [
            "--path",
            str(tmp_path),
            "--title",
            "Use PostgreSQL",
            "--domain",
            "Backend",
            "--scope",
            "Data",
            "--refdate",
            "2026-01-01",
        ]
    )
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-use-postgre-sql.md"
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    return tmp_path, adr_path


def test_revise_still_fails_safely_when_lenrevision_races_to_zero_after_the_pre_lock_read(tmp_path, monkeypatch):
    """Investigated and ruled out, not a live bug
    -- kept as a permanent regression test per this project's own rule
    that a checked hypothesis becomes a test. revise's early eligibility
    gate (`if config.lenrevision == 0`) reads config BEFORE the lock,
    same chicken-and-egg as folderadr; nothing re-verifies it against the
    fresh post-lock config the way the folderadr fix does. A concurrent
    `config --lenrevision 0` mid-flight was suspected to let revise write
    a revision the repository no longer supports. It does not: the fresh
    config IS used for the lenrevision-fits-the-digit-count check further
    down (line ~118), and any new revision number has at least 1 digit,
    so `len(str(new_revision)) > lenrevision` is always true once
    lenrevision has raced down to 0 -- an accidental but real backstop,
    not a designed one. The error code this produces
    (lenrevision-too-small-for-new-revision) is misleading given the real
    cause, but no data corruption occurs and no write is made."""
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    stale_config = load_repo_config(tmp_path / "adr-config.adrplus")
    assert stale_config.lenrevision == 2

    real_resolve = revise.resolve_repo_and_target

    def stale_resolve(fileadr):
        _config, root, path = real_resolve(fileadr)
        return stale_config, root, path

    monkeypatch.setattr(revise, "resolve_repo_and_target", stale_resolve)

    # Concurrently (from this test's perspective) disable revisions
    # entirely -- the on-disk config is what the fresh post-lock read
    # will see; the patched resolve_repo_and_target above still hands
    # revise the stale lenrevision=2 value for its early pre-lock check.
    config.run(["--path", str(tmp_path), "--lenrevision", "0"])

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "lenrevision-too-small-for-new-revision"
    # No new revision file was created.
    assert not (tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md").exists()


def test_revise_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """See version's own
    equivalent test."""
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
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
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "family-scan-incomplete"
    assert not (adr_dir / "ADR001V01R02-use-postgre-sql.md").exists()  # no write made


def test_revise_reports_source_unchanged_when_encoding_was_repaired(tmp_path):
    """Same class as
    version's own test: revise never rewrites its own source either."""
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")
    source_bytes_before = adr_path.read_bytes()

    result = revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert not any("rewritten" in w.lower() for w in result["warnings"])
    assert any("utf-8" in w.lower() and str(adr_path) in w for w in result["warnings"])
    assert adr_path.read_bytes() == source_bytes_before  # source genuinely untouched


def test_revise_happy_path(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)

    result = revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    new_path = tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md"
    assert result["created"] == str(new_path)
    text = new_path.read_text(encoding="utf-8")
    assert "|Version|01|" in text  # version unchanged
    assert "|Revision|02|" in text
    assert "|Domain|Backend|" in text  # target's own value
    assert "|Created|Proposed (2026-01-05) <!-- Proposed -->|" in text


def test_revise_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage.
    ADR006V01: revise's own write goes through atomic_write_chunks, not
    atomic_write_text."""
    from adrpy.cli import revise as revise_module

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    real_atomic_write_chunks = revise_module.atomic_write_chunks

    def flaky_atomic_write_chunks(*args, **kwargs):
        real_atomic_write_chunks(*args, **kwargs)
        return 3

    monkeypatch.setattr(revise_module, "atomic_write_chunks", flaky_atomic_write_chunks)

    result = revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert any("3 attempts" in w for w in result["warnings"])


def test_revise_scans_the_directory_only_once(tmp_path, monkeypatch):
    """Performance backlog item: latest_in_family, has_superseded_sibling,
    and has_pending_sibling each called family_members (and so
    scan_decisions) independently -- 3 full directory scans per revise
    call for information a single scan already has."""
    from adrpy.core import lifecycle

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)

    calls = []
    original = lifecycle.scan_decisions

    def counting_scan_decisions(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "scan_decisions", counting_scan_decisions)

    revise.run(["--file", str(adr_path)])

    assert len(calls) == 1


def test_revise_rejects_when_revisions_not_configured(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "No revisions here"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-no-revisions-here.md"
    approve.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    assert excinfo.value.code == "revision-not-configured"


def test_revise_rejects_when_not_accepted_or_rejected(tmp_path):
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_config_with_revisions()), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    new.run(["--path", str(tmp_path), "--title", "Still proposed"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-still-proposed.md"

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"


def test_revise_rejects_when_sibling_superseded(tmp_path):
    """Family-member-superseded
    is raised by hand at 8 call sites across 5 command files; revise's
    own had zero coverage. Target is R02 (latest, Accepted); a lower,
    non-latest sibling R01 carries status_change=Superseded."""
    tmp_path, _ = _setup_accepted_repo_with_revisions(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"

    sibling_path = adr_dir / "ADR001V01R01-use-postgre-sql.md"
    sibling_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        revision=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 2),
        superseded_by_file="999",
    )
    atomic_write_text(sibling_path, build_header(config, sibling_record) + "# body")

    target_path = adr_dir / "ADR001V01R02-use-postgre-sql.md"
    target_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        revision=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(target_path, build_header(config, target_record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(target_path)])

    assert excinfo.value.code == "family-member-superseded"


def test_revise_rejects_when_sibling_pending(tmp_path):
    """Same class as the superseded case above, for family-member-pending."""
    tmp_path, _ = _setup_accepted_repo_with_revisions(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"

    sibling_path = adr_dir / "ADR001V01R01-use-postgre-sql.md"
    sibling_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        revision=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
    )
    atomic_write_text(sibling_path, build_header(config, sibling_record) + "# body")

    target_path = adr_dir / "ADR001V01R02-use-postgre-sql.md"
    target_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        revision=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(target_path, build_header(config, target_record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(target_path)])

    assert excinfo.value.code == "family-member-pending"


def test_revise_prioritizes_superseded_sibling_over_pending_sibling(tmp_path):
    """Superseded takes priority over pending, deliberately -- a superseded
    member means the WHOLE family has already been replaced, which
    blocks it regardless of any other sibling's own state. No existing
    test constructed a family with BOTH conditions true at once."""
    tmp_path, _ = _setup_accepted_repo_with_revisions(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"

    # Both siblings must stay BELOW the target's own (version, revision),
    # or either one would itself become "the latest" and the
    # not-latest-version check earlier in revise.run() would fire first,
    # never reaching the sibling checks this test actually targets.
    superseded_sibling = adr_dir / "ADR001V01R01-use-postgre-sql.md"
    superseded_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        revision=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 2),
        superseded_by_file="999",
    )
    atomic_write_text(superseded_sibling, build_header(config, superseded_record) + "# body")

    pending_sibling = adr_dir / "ADR001V01R02-use-postgre-sql.md"
    pending_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        revision=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
    )
    atomic_write_text(pending_sibling, build_header(config, pending_record) + "# body")

    target_path = adr_dir / "ADR001V01R03-use-postgre-sql.md"
    target_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        revision=3,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(target_path, build_header(config, target_record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(target_path)])

    assert excinfo.value.code == "family-member-superseded"


def test_revise_rejects_when_not_latest_and_latest_not_rejected(tmp_path):
    """not-latest-version must name WHICH revision
    actually is the latest -- see `version`'s own equivalent test."""
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    r2_path = tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md"
    approve.run(["--file", str(r2_path), "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == str(r2_path)
    assert excinfo.value.data["latest_revision"] == 2
    assert excinfo.value.data["latest_status"] == "Accepted"


def test_revise_branching_from_immediate_predecessor_of_a_rejected_latest_collides(tmp_path):
    """Confirmed against a real run of the reference tool's own `revise`
    command: revise's new revision
    number is always TARGET.revision+1 (never latest.revision+1, unlike
    `version`'s always-fresh latest.version+1) -- so branching off the
    revision immediately before a rejected latest recomputes that exact
    same (now-rejected-but-still-on-disk) filename and collides. This is
    the reference tool's own behavior, not a bug in this port: the branch-off
    exception is only usable when the recomputed number doesn't already
    exist (e.g. branching from further back, or after the intervening
    files are otherwise gone)."""
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    r2_path = tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md"
    reject.run(["--file", str(r2_path), "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": "ADR001V01R02-use-postgre-sql.md"}


def test_revise_rejects_when_lenrevision_too_small_for_new_revision(tmp_path):
    data = _config_with_revisions()
    data["lenrevision"] = 1
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"
    record = DecisionRecord(
        number=1,
        title="Existing",
        version=1,
        revision=9,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    adr_path = adr_dir / "ADR001V01R9-existing.md"
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "lenrevision-too-small-for-new-revision"
    assert excinfo.value.data == {"new_revision": 10, "lenrevision": 1}


def test_revise_rejects_refdate_before_latest_date(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-01"])

    assert excinfo.value.code == "refdate-before-history"


def test_revise_rejects_refdate_in_future(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", future])

    assert excinfo.value.code == "refdate-in-future"


def test_revise_rejects_path_traversal_via_header_title(tmp_path):
    """Same class as version's own finding -- revise's
    new record's title also comes straight from the target's already-
    parsed header cell. Caught by reject_filesystem_unsafe_title/
    reject_embedded_delimiter before build_filename is ever called;
    resolve_within remains a second,
    independent line of defense against anything those checks might
    miss."""
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_config_with_revisions()), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-placeholder.md"
    record = DecisionRecord(
        number=1,
        title="../../../outside",
        version=1,
        revision=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    assert excinfo.value.code == "field-contains-forbidden-character"
    assert not (tmp_path.parent / "outside.md").exists()


@pytest.mark.parametrize("field", ["scope", "domain"])
def test_revise_rejects_a_control_character_in_scope_or_domain_read_from_the_target_header(tmp_path, field):
    """Unlike `version`, which re-validates scope/domain even when they fall
    back to the latest member's own current value, revise never validated
    them at all -- they come straight from the target's already-parsed
    header cell, carried forward into the new revision's own header with
    zero checking. Confirmed live: a hand-edited '\\x0b' (VT) in the Scope
    cell survived an unrelated `revise` call unchanged, propagating into
    the new revision's own header and into `explore`'s own JSON output --
    the exact data-hygiene defect reject_embedded_delimiter's own
    blacklist exists to prevent, just never wired up for this command's
    two fields. (Embedding a literal '|' instead does not forge the table
    the same way: `_extract_cell`'s own read-side parsing already
    truncates a cell's value at the first '|', so it can never actually
    reach `header.scope`/`header.domain` as a raw character -- confirmed
    directly, which is why this test uses a control character instead,
    the vector that DOES survive the round-trip.)"""
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_config_with_revisions()), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-placeholder.md"
    record = DecisionRecord(
        number=1,
        title="placeholder",
        version=1,
        revision=1,
        scope="bad\x0bscope" if field == "scope" else "goodscope",
        domain="bad\x0bdomain" if field == "domain" else "gooddomain",
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_revise_rejects_a_header_title_made_only_of_separator_characters(tmp_path):
    """to_case (core/casing.py) falls back to
    echoing its raw input unchanged when word-splitting finds nothing to
    transform, which happens exactly when the title is made entirely of
    whitespace/'_'/'-' -- reachable here via a hand-edited or migrated
    source file's header cell, same as the path-traversal case above."""
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_config_with_revisions()), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-placeholder.md"
    record = DecisionRecord(
        number=1,
        title="---",
        version=1,
        revision=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_revise_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)

    assert main(["revise", "--file", str(adr_path)]) == EXIT_SUCCESS


def test_revise_describe_documents_the_lenrevision_precondition():
    """Revise fails with revision-not-configured on
    any freshly-init'd repository (100% of the time, not an edge case) --
    describe() never said so, so an agent only discovered this by trial
    and error."""
    assert "lenrevision" in revise.describe()["description"]
