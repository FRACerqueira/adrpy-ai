import json
import os
from datetime import date, timedelta

from adrpy.cli import approve, init, new, reject, revise
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

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]
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
    """The repository is read once per call: one scan of the decisions
    folder (core/consistency), whose snapshot feeds the target, its family
    and every guard -- no second scan."""
    from adrpy.core import consistency

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)

    calls = []
    original = consistency.scan_tree

    def counting_scan_tree(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(consistency, "scan_tree", counting_scan_tree)

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
    """family-member-superseded, reached with tool commands only: R02 was
    rejected, which left R01 live, and R01 was then superseded. Revising
    R02 (Rejected, eligible for revise) is refused."""
    from adrpy.cli import supersede

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    r02 = revise.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    reject.run(["--file", r02, "--refdate", "2026-01-04"])
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", r02, "--refdate", "2026-01-06"])

    assert excinfo.value.code == "family-member-superseded"


def test_revise_rejects_when_sibling_pending(tmp_path):
    """family-member-pending, reached with tool commands only: R02 is still
    Proposed when R01 is revised again."""
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    revise.run(["--file", str(adr_path), "--refdate", "2026-01-03"])

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-04"])

    assert excinfo.value.code == "family-member-pending"


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
    assert sorted(p.name for p in r2_path.parent.glob("*.md")) == [adr_path.name, r2_path.name]


def test_revise_branching_off_an_older_revision_takes_the_next_free_number(tmp_path):
    """Round 40, decided by the project owner (a divergence from AdrPlus,
    whose revise always computes TARGET.revision+1 and so collided here
    with the rejected R02 still on disk): revise numbers from the highest
    revision this version already holds, so branching off R01 while the
    single newer R02 is Rejected creates R03."""
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    r2_path = tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md"
    reject.run(["--file", str(r2_path), "--refdate", "2026-01-06"])

    result = revise.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert os.path.basename(result["created"]) == "ADR001V01R03-use-postgre-sql.md"


def test_revise_of_a_migrated_placeholder_numbers_from_its_filename(tmp_path):
    # A migrated placeholder's Version/Revision cells are blank; the
    # filename decides numbering, so V02R01 is followed by V02R02, never V00.
    import sys
    sys.path.insert(0, os.path.dirname(__file__))
    from adrpy.cli import migrate

    config_file = tmp_path / "seed-config.json"
    config = dict(_config_with_revisions(), migrationpattern="N00:04T08V04:02R06:02")
    config_file.write_text(json.dumps(config), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    legacy = adr_dir / "00010201Foo.md"
    legacy.write_bytes(b"# Foo\n\nbody\n")
    migrate.run(["--path", str(tmp_path)])

    result = revise.run(["--file", str(legacy), "--refdate", "2026-01-07"])

    assert os.path.basename(result["created"]) == "ADR001V02R02-foo.md"


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

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")
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

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")


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

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")


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


def test_revise_refuses_a_revision_number_held_by_a_file_whose_header_does_not_parse(tmp_path):
    # An R02 with no header is a broken repository rule (no-header): revise
    # refuses, never creating a second R02.
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    broken = adr_path.parent / "ADR001V01R02-draft.md"
    broken.write_text("no header\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-03"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [(e["code"], e["file"]) for e in excinfo.value.data["errors"]] == [("no-header", str(broken.resolve()))]
    assert sorted(p.name for p in adr_path.parent.glob("ADR001V01R02*")) == ["ADR001V01R02-draft.md"]


def test_revise_never_reuses_a_revision_number_a_valid_file_holds(tmp_path):
    # Branching off R01 while R02 (Rejected) exists: a hand-edited title
    # gives the new file a different name, which an identical-name check
    # alone would miss -- numbering past the highest revision never reuses R02.
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    r2_path = tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md"
    reject.run(["--file", str(r2_path), "--refdate", "2026-01-06"])
    text = adr_path.read_text(encoding="utf-8")
    title_row = [line for line in text.splitlines() if line.startswith("|File title md|")][0]
    adr_path.write_text(text.replace(title_row, "|File title md|Renamed|"), encoding="utf-8")

    result = revise.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert os.path.basename(result["created"]) == "ADR001V01R03-renamed.md"
    assert sorted(p.name for p in r2_path.parent.glob("ADR001V01R02*")) == [r2_path.name]



def test_revise_numbering_only_counts_revisions_of_its_own_version(tmp_path):
    # Positive control: an R02 in version 1 does not affect version 2.
    from adrpy.cli import version

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    r02 = revise.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    approve.run(["--file", r02, "--refdate", "2026-01-04"])
    v02 = version.run(["--file", r02, "--refdate", "2026-01-05"])["created"]
    approve.run(["--file", v02, "--refdate", "2026-01-06"])

    result = revise.run(["--file", v02, "--refdate", "2026-01-07"])

    assert os.path.basename(result["created"]) == "ADR001V02R02-use-postgre-sql.md"



def test_revise_of_a_file_outside_the_decisions_folder_is_refused(tmp_path):
    # Only a decision inside the configured decisions folder is acted on
    # (target-outside-folderadr); nothing is written, here or there.
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    outside = elsewhere / "ADR001V02R01-use-postgre-sql.md"
    outside.write_bytes(adr_path.read_bytes())
    before = sorted(p.name for p in adr_path.parent.iterdir())

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(outside), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "target-outside-folderadr"
    assert sorted(p.name for p in adr_path.parent.iterdir()) == before
    assert [p.name for p in elsewhere.iterdir()] == [outside.name]



def test_revise_of_a_rejected_successor_is_final(tmp_path):
    from adrpy.cli import supersede

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    succ = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    reject.run(["--file", succ, "--refdate", "2026-01-04"])
    before = sorted(p.name for p in adr_path.parent.glob("*.md"))

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", succ, "--refdate", "2026-01-05"])

    assert excinfo.value.code == "rejected-successor-is-final"
    assert sorted(p.name for p in adr_path.parent.glob("*.md")) == before


def test_a_newer_revision_still_locks_when_the_newer_version_is_rejected(tmp_path):
    from adrpy.cli import undo, version

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    r02 = revise.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    approve.run(["--file", r02, "--refdate", "2026-01-04"])
    v02 = version.run(["--file", r02, "--refdate", "2026-01-05"])["created"]
    reject.run(["--file", v02, "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == r02


def test_a_newer_version_is_not_locked_by_an_older_versions_higher_revision(tmp_path):
    from adrpy.cli import version

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    r02 = revise.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    approve.run(["--file", r02, "--refdate", "2026-01-04"])
    v02 = version.run(["--file", r02, "--refdate", "2026-01-05"])["created"]

    assert approve.run(["--file", v02, "--refdate", "2026-01-06"])["status"] == "Accepted"


def test_not_latest_names_the_highest_revision_of_the_newest_version(tmp_path):
    from adrpy.cli import undo, version

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    v02r01 = version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    approve.run(["--file", v02r01, "--refdate", "2026-01-04"])
    v02r02 = revise.run(["--file", v02r01, "--refdate", "2026-01-05"])["created"]
    approve.run(["--file", v02r02, "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.data["latest_file"] == v02r02


def test_revise_numbers_a_migrated_placeholder_by_its_filename_version(tmp_path):
    from adrpy.cli import migrate

    config_file = tmp_path / "seed-config.json"
    config = dict(_config_with_revisions(), migrationpattern="N00:04T08V04:02R06:02")
    config_file.write_text(json.dumps(config), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    r01, r02 = adr_dir / "00010201Foo.md", adr_dir / "00010202Foo.md"
    for path in (r01, r02):
        path.write_bytes(b"# Foo\n\nbody\n")
    migrate.run(["--path", str(tmp_path)])
    reject.run(["--file", str(r02), "--refdate", "2026-01-05"])
    approve.run(["--file", str(r01), "--refdate", "2026-01-05"])

    result = revise.run(["--file", str(r01), "--refdate", "2026-01-06"])

    assert os.path.basename(result["created"]) == "ADR001V02R03-foo.md"



