import os
from pathlib import Path
from datetime import date, timedelta

from adrpy.cli import approve, init, new, reject, version
from adrpy.core.atomic_write import atomic_write_text
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header

import pytest


def _setup_accepted_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
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
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    return tmp_path, adr_path


def test_version_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """End to end: an unreadable subdirectory stops this command through
    the repository validation (scan-incomplete), with no write made."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
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
        version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]
    assert not (adr_dir / "ADR001V02-use-postgre-sql.md").exists()  # no write made


def test_version_rejects_when_lenversion_too_small_for_new_version(tmp_path):
    init.run(["--path", str(tmp_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"
    record = DecisionRecord(
        number=1,
        title="Existing",
        version=99,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    adr_path = adr_dir / "ADR001V99-existing.md"
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "lenversion-too-small-for-new-version"
    # The real number was only ever in `detail`
    # (stderr, free text).
    assert excinfo.value.data == {"new_version": 100, "lenversion": 2}
    # The way out is widening lenversion, by name.
    assert "`adrpy config --path <repository> --lenversion 3`" in excinfo.value.detail
    from adrpy.cli import config as config_cmd

    config_cmd.run(["--path", str(tmp_path), "--lenversion", "3"])
    assert version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])["created"].endswith("ADR001V100-existing.md")


def test_version_checks_the_targets_status_before_the_new_number_fits(tmp_path):
    # Like every other command, the target's own status comes first: a
    # Proposed V99 is refused as still-proposed, not as a width problem
    # the owner could "fix" by widening lenversion.
    init.run(["--path", str(tmp_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    record = DecisionRecord(number=1, title="Existing", version=99, status_create="Proposed", date_create=date(2026, 1, 1))
    adr_path = tmp_path / "doc" / "adr" / "ADR001V99-existing.md"
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "still-proposed"


def test_version_checks_the_family_rules_before_the_new_number_fits(tmp_path):
    # The numbering comes last: V98 locked by an Accepted V99 is refused
    # as not-latest-version, not as a width problem that widening
    # lenversion would only trade for this same refusal.
    init.run(["--path", str(tmp_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    folder = tmp_path / "doc" / "adr"
    for number in (98, 99):
        record = DecisionRecord(
            number=1, title="Existing", version=number, status_create="Proposed", date_create=date(2026, 1, 1),
            status_update="Accepted", date_update=date(2026, 1, 2),
        )
        atomic_write_text(folder / f"ADR001V{number}-existing.md", build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(folder / "ADR001V98-existing.md"), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "not-latest-version"


def test_lenversion_one_below_the_maximum_offers_config_up_to_the_maximum(tmp_path):
    # The boundary of the widening hint: the width needed equals the
    # maximum, which config accepts -- so the hint offers config.
    from adrpy.cli import config as config_cmd
    from adrpy.core.config import LENVERSION_MAX

    init.run(["--path", str(tmp_path)])
    config_cmd.run(["--path", str(tmp_path), "--lenversion", str(LENVERSION_MAX - 1)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    last = 10 ** (LENVERSION_MAX - 1) - 1
    record = DecisionRecord(
        number=1,
        title="Existing",
        version=last,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    adr_path = tmp_path / "doc" / "adr" / f"ADR001V{last}-existing.md"
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "lenversion-too-small-for-new-version"
    assert f"`adrpy config --path <repository> --lenversion {LENVERSION_MAX}`" in excinfo.value.detail
    config_cmd.run(["--path", str(tmp_path), "--lenversion", str(LENVERSION_MAX)])
    created = version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])["created"]
    assert created.endswith(f"ADR001V{last + 1}-existing.md")


def test_lenversion_too_small_at_the_maximum_width_offers_no_config_way_out(tmp_path):
    # At lenversion's maximum, config would refuse a wider value
    # (config-lenversion-too-large): the detail must not suggest it.
    from adrpy.core.config import LENVERSION_MAX

    init.run(["--path", str(tmp_path)])
    config_path = tmp_path / "adr-config.adrplus"
    from adrpy.cli import config as config_cmd

    config_cmd.run(["--path", str(tmp_path), "--lenversion", str(LENVERSION_MAX)])
    config = load_repo_config(config_path)
    record = DecisionRecord(
        number=1,
        title="Existing",
        version=10**LENVERSION_MAX - 1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    adr_path = tmp_path / "doc" / "adr" / f"ADR001V{10**LENVERSION_MAX - 1}-existing.md"
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "lenversion-too-small-for-new-version"
    assert "adrpy config" not in excinfo.value.detail
    assert f"maximum ({LENVERSION_MAX})" in excinfo.value.detail


def test_version_reports_the_colliding_filename_as_data_when_it_already_exists(tmp_path, monkeypatch):
    """The TOCTOU race the exclusive create defends against: the file is
    created after this call's snapshot was taken (any file already there
    is in the snapshot, and numbering moves past it)."""
    from adrpy.core import lifecycle as lifecycle_module

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    colliding_path = tmp_path / "doc" / "adr" / "ADR001V02-use-postgre-sql.md"
    real_validate = lifecycle_module.validate_repository

    def validate_then_collide(folder, config, scan=None):
        snapshot = real_validate(folder, config, scan)
        colliding_path.write_text("already here", encoding="utf-8")
        return snapshot

    monkeypatch.setattr(lifecycle_module, "validate_repository", validate_then_collide)

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": "ADR001V02-use-postgre-sql.md"}


def test_version_reports_source_unchanged_when_encoding_was_repaired(tmp_path):
    """encoding_repaired_
    warning unconditionally claimed "the file has been rewritten... bytes
    are now lost" -- always false here, since version never rewrites its
    own source (only its BODY is carried into a newly created file)."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")
    source_bytes_before = adr_path.read_bytes()

    result = version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert not any("rewritten" in w.lower() for w in result["warnings"])
    assert any("utf-8" in w.lower() and str(adr_path) in w for w in result["warnings"])
    assert adr_path.read_bytes() == source_bytes_before  # source genuinely untouched


def test_version_happy_path(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    result = version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    new_path = tmp_path / "doc" / "adr" / "ADR001V02-use-postgre-sql.md"
    assert result["created"] == str(new_path)
    assert result["status"] == "Proposed"
    text = new_path.read_text(encoding="utf-8")
    assert "|File title md|Use PostgreSQL|" in text  # header prose title, not filename
    assert "|Version|02|" in text
    assert "|Domain|Backend|" in text  # inherited from latest
    assert "|Scope|Data|" in text
    assert "|Created|Proposed (2026-01-05) <!-- Proposed -->|" in text
    assert "# body" not in text  # body carried forward from the source (template, not literal marker)
    # No test pinned the exact
    # empty-list value on a genuine happy path, only that the key exists.
    assert result["warnings"] == []


def test_version_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage.
    ADR006V01: version's own (non---empty) write goes through
    atomic_write_chunks, not atomic_write_text."""
    from adrpy.cli import version as version_module

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    real_atomic_write_chunks = version_module.atomic_write_chunks

    def flaky_atomic_write_chunks(*args, **kwargs):
        real_atomic_write_chunks(*args, **kwargs)
        return 3

    monkeypatch.setattr(version_module, "atomic_write_chunks", flaky_atomic_write_chunks)

    result = version.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_version_scans_the_directory_only_once(tmp_path, monkeypatch):
    """The repository is read once per call: one scan of the decisions
    folder (taken in prepare(), feeding the orphan sweep and core/consistency),
    whose snapshot feeds the target, its family
    and every guard -- no second scan."""
    from adrpy.core import consistency, lifecycle

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    calls = []
    original = consistency.scan_tree

    def counting_scan_tree(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(consistency, "scan_tree", counting_scan_tree)
    monkeypatch.setattr(lifecycle, "scan_tree", counting_scan_tree)

    version.run(["--file", str(adr_path)])

    assert len(calls) == 1


def test_version_rejects_when_not_accepted_or_rejected(tmp_path):
    tmp_path = tmp_path
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Still proposed"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-still-proposed.md"

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"


def test_version_rejects_when_sibling_superseded(tmp_path):
    """family-member-superseded, reached with tool commands only: V02 was
    rejected, which left V01 live, and V01 was then superseded. Branching
    V02 (Rejected, eligible for version) is refused."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    v02 = version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    reject.run(["--file", v02, "--refdate", "2026-01-04"])
    from adrpy.cli import supersede

    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", v02, "--refdate", "2026-01-06"])

    assert excinfo.value.code == "family-member-superseded"
    assert excinfo.value.data["superseded_file"] == str(adr_path.resolve())
    # The successor's number as an int, not the raw Superseded cell text.
    assert excinfo.value.data["successor_number"] == 2


def test_version_rejects_when_sibling_pending(tmp_path):
    """family-member-pending, reached with tool commands only: V02 is
    still Proposed when V01 is branched again (the pending guard comes
    before not-latest-version)."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    v02 = version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-04"])

    assert excinfo.value.code == "family-member-pending"
    assert excinfo.value.data["pending_file"] == str(Path(v02).resolve())


def test_version_rejects_when_not_latest_and_latest_not_rejected(tmp_path):
    """not-latest-version must name WHICH version
    actually is the latest -- a fixed code can't carry that number, so
    it travels as structured `data` on the CommandError instead."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    v2_path = tmp_path / "doc" / "adr" / "ADR001V02-use-postgre-sql.md"
    approve.run(["--file", str(v2_path), "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == str(v2_path)
    assert excinfo.value.data["latest_version"] == 2
    assert excinfo.value.data["latest_status"] == "Accepted"


def test_not_latest_version_names_the_newest_live_member_not_a_newer_rejected_one(tmp_path):
    """V02 (Accepted) locks V01; V03 is newer but Rejected, so it locks
    nothing -- data.latest_file must name V02, the member that does."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    v2_path = version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    approve.run(["--file", v2_path, "--refdate", "2026-01-04"])
    v3_path = version.run(["--file", v2_path, "--refdate", "2026-01-05"])["created"]
    reject.run(["--file", v3_path, "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == str(Path(v2_path).resolve())
    assert excinfo.value.data["latest_version"] == 2


def test_version_allows_branching_from_older_when_latest_rejected(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    v2_path = tmp_path / "doc" / "adr" / "ADR001V02-use-postgre-sql.md"
    reject.run(["--file", str(v2_path), "--refdate", "2026-01-06"])

    result = version.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    v3_path = tmp_path / "doc" / "adr" / "ADR001V03-use-postgre-sql.md"
    assert result["created"] == str(v3_path)


def test_version_with_empty_uses_default_template(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    result = version.run(["--file", str(adr_path), "--empty"])

    text = open(result["created"], encoding="utf-8").read()
    assert "[Brief title of the decision]" in text  # the default template's own placeholder text


def test_version_rejects_refdate_before_latest_date(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-01"])

    assert excinfo.value.code == "refdate-before-history"


def test_version_rejects_refdate_in_future(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", future])

    assert excinfo.value.code == "refdate-in-future"


def test_version_can_override_scope_and_domain(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    result = version.run(["--file", str(adr_path), "--domain", "Platform", "--scope", "Infra"])

    text = open(result["created"], encoding="utf-8").read()
    assert "|Domain|Platform|" in text
    assert "|Scope|Infra|" in text


def test_version_rejects_embedded_delimiter(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--scope", "Bad|scope"])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_version_rejects_embedded_delimiter_in_domain(tmp_path):
    """--domain needs its own '|'-rejection coverage, distinct from
    --scope's: it goes through the exact same reject_embedded_delimiter
    call one line below."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--domain", "Bad|domain"])

    assert excinfo.value.code == "field-contains-forbidden-character"


@pytest.mark.parametrize("flag", ["domain", "scope"])
def test_version_rejects_a_whitespace_only_value(tmp_path, flag):
    """A whitespace-only value must not be written verbatim into the new
    version's header cell."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), f"--{flag}", "   "])

    assert excinfo.value.code == "field-is-blank"


def test_version_rejects_path_traversal_via_header_title(tmp_path):
    """Unlike --title on `new`, version/revise/supersede
    source the new record's title from the target's already-parsed header
    cell -- a crafted header title reaches build_filename the exact same
    way a hostile --title does. Caught by reject_filesystem_unsafe_title/
    reject_embedded_delimiter before build_filename is ever called;
    resolve_within remains a second,
    independent line of defense against anything those checks might
    miss."""
    init.run(["--path", str(tmp_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-placeholder.md"
    record = DecisionRecord(
        number=1,
        title="../../../outside",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")
    assert not (tmp_path.parent / "outside.md").exists()


def test_version_rejects_a_header_title_made_only_of_separator_characters(tmp_path):
    """to_case (core/casing.py) falls back to
    echoing its raw input unchanged when word-splitting finds nothing to
    transform, which happens exactly when the title is made entirely of
    whitespace/'_'/'-' -- reachable here via a hand-edited or migrated
    source file's header cell, the same as the path-traversal case above."""
    init.run(["--path", str(tmp_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-placeholder.md"
    record = DecisionRecord(
        number=1,
        title="---",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")


def test_version_accepts_relative_file_path(tmp_path, monkeypatch):
    """Regression: `latest_path != path` must resolve both sides -- a
    relative --file argument must still be recognized as the latest."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    monkeypatch.chdir(tmp_path)

    result = version.run(["--file", "doc/adr/ADR001V01-use-postgre-sql.md"])

    assert result["status"] == "Proposed"


def test_version_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    assert main(["version", "--file", str(adr_path)]) == EXIT_SUCCESS


def test_version_describe_declares_empty_as_a_presence_only_switch():
    """--empty is presence-only (confirmed live,
    `--empty true` fails with "Unknown argument") -- must not be declared
    "boolean", which implies accepting an explicit value like
    `config --disableplugins true/false` does."""
    arguments = {argument["name"]: argument for argument in version.describe()["arguments"]}

    assert arguments["empty"]["type"] == "switch"


def test_version_refuses_a_number_held_by_a_file_whose_header_does_not_parse(tmp_path):
    # The filename decides numbering: a V02 with no header is a broken
    # repository rule (no-header), so version refuses instead of creating
    # a second V02 under another title.
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    broken = adr_path.parent / "ADR001V02-draft.md"
    broken.write_text("no header\n", encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [(e["code"], e["file"]) for e in excinfo.value.data["errors"]] == [("no-header", str(broken.resolve()))]
    assert sorted(p.name for p in adr_path.parent.glob("ADR001V02*")) == ["ADR001V02-draft.md"]



def test_version_takes_its_defaults_from_the_target_not_a_rejected_newer_member(tmp_path):
    # Round 41 (K1a): branching off V01 while V02 was rejected, the new
    # version's scope/domain default to V01's, and --refdate is bounded by
    # V01's own dates, not V02's.
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    v02 = version.run(["--file", str(adr_path), "--refdate", "2026-01-10", "--scope", "Other", "--domain", "Elsewhere"])["created"]
    reject.run(["--file", v02, "--refdate", "2026-01-12"])

    result = version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    text = Path(result["created"]).read_text(encoding="utf-8")
    assert "|Scope|Data|" in text and "|Domain|Backend|" in text



def test_version_scope_and_domain_default_to_the_target_even_with_a_later_refdate(tmp_path):
    # Isolates the defaults from the refdate bound: the date is after every
    # date in the family, so only the scope/domain source is under test.
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    v02 = version.run(["--file", str(adr_path), "--refdate", "2026-01-10", "--scope", "Other", "--domain", "Elsewhere"])["created"]
    reject.run(["--file", v02, "--refdate", "2026-01-12"])

    text = Path(version.run(["--file", str(adr_path), "--refdate", "2026-01-20"])["created"]).read_text(encoding="utf-8")

    assert "|Scope|Data|" in text and "|Domain|Backend|" in text


def test_version_checks_the_new_version_width_after_refdate(tmp_path):
    # Owner rule: the new number is checked last in every command (as
    # new/supersede do with lenseq), so a bad --refdate is reported
    # before a lenversion that widening would only trade for it.
    init.run(["--path", str(tmp_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    record = DecisionRecord(
        number=1,
        title="Existing",
        version=99,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    adr_path = tmp_path / "doc" / "adr" / "ADR001V99-existing.md"
    atomic_write_text(adr_path, build_header(config, record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2025-12-31"])

    assert excinfo.value.code == "refdate-before-history"
