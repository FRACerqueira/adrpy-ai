import os
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
    """Decision log claims this command "inherit[s] [the family_members
    fail-closed fix] for free" -- but nothing end-to-end proved that.
    Demonstrated: wrapping this command's own family_members call in
    try/except CommandError left the full suite green with no test
    noticing."""
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

    assert excinfo.value.code == "family-scan-incomplete"
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


def test_version_reports_the_colliding_filename_as_data_when_it_already_exists(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    colliding_path = tmp_path / "doc" / "adr" / "ADR001V02-use-postgre-sql.md"
    colliding_path.write_text("already here", encoding="utf-8")

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
    assert "|Created|Proposed (2026-01-05)|" in text
    assert "# body" not in text  # body carried forward from the source (template, not literal marker)
    # No test pinned the exact
    # empty-list value on a genuine happy path, only that the key exists.
    assert result["warnings"] == []


def test_version_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage."""
    from adrpy.cli import version as version_module

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    real_atomic_write_text = version_module.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(version_module, "atomic_write_text", flaky_atomic_write_text)

    result = version.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_version_scans_the_directory_only_once(tmp_path, monkeypatch):
    """Performance backlog item: latest_in_family, has_superseded_sibling,
    and has_pending_sibling each called family_members (and so
    scan_decisions) independently -- 3 full directory scans per version
    call for information a single scan already has."""
    from adrpy.core import lifecycle

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    calls = []
    original = lifecycle.scan_decisions

    def counting_scan_decisions(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "scan_decisions", counting_scan_decisions)

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
    """Family-member-superseded
    is raised by hand at 8 call sites across 5 command files; version's
    own had zero coverage. Target is V02 (latest, Accepted); a lower,
    non-latest sibling V01 carries status_change=Superseded."""
    tmp_path, _ = _setup_accepted_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"

    sibling_path = adr_dir / "ADR001V01-use-postgre-sql.md"
    sibling_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 2),
        superseded_by_file="999",
    )
    atomic_write_text(sibling_path, build_header(config, sibling_record) + "# body")

    target_path = adr_dir / "ADR001V02-use-postgre-sql.md"
    target_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(target_path, build_header(config, target_record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(target_path)])

    assert excinfo.value.code == "family-member-superseded"


def test_version_rejects_when_sibling_pending(tmp_path):
    """Same class as the superseded case above, for family-member-pending."""
    tmp_path, _ = _setup_accepted_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"

    sibling_path = adr_dir / "ADR001V01-use-postgre-sql.md"
    sibling_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
    )
    atomic_write_text(sibling_path, build_header(config, sibling_record) + "# body")

    target_path = adr_dir / "ADR001V02-use-postgre-sql.md"
    target_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(target_path, build_header(config, target_record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(target_path)])

    assert excinfo.value.code == "family-member-pending"


def test_version_prioritizes_superseded_sibling_over_pending_sibling(tmp_path):
    """Superseded takes priority over pending, deliberately -- a superseded
    member means the WHOLE family has already been replaced, which
    blocks it regardless of any other sibling's own state. No existing
    test constructed a family with BOTH conditions true at once."""
    tmp_path, _ = _setup_accepted_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"

    # Both siblings must stay BELOW the target's own version, or either one
    # would itself become "the latest" and the not-latest-version check
    # earlier in version.run() would fire first, never reaching the
    # sibling checks this test actually targets.
    superseded_sibling = adr_dir / "ADR001V01-use-postgre-sql.md"
    superseded_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 2),
        superseded_by_file="999",
    )
    atomic_write_text(superseded_sibling, build_header(config, superseded_record) + "# body")

    pending_sibling = adr_dir / "ADR001V02-use-postgre-sql.md"
    pending_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
    )
    atomic_write_text(pending_sibling, build_header(config, pending_record) + "# body")

    target_path = adr_dir / "ADR001V03-use-postgre-sql.md"
    target_record = DecisionRecord(
        number=1,
        title="Use PostgreSQL",
        version=3,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    atomic_write_text(target_path, build_header(config, target_record) + "# body")

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(target_path)])

    assert excinfo.value.code == "family-member-superseded"


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
    cell (never delimiter-checked on read) -- a crafted header title
    reaches build_filename the exact same way a hostile --title does.
    Confirmed live: a hand-crafted header with '../../../../HDR-PWNED' as
    its title made the real `version` write a file outside the repo."""
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

    assert excinfo.value.code == "path-outside-repository"
    assert not (tmp_path.parent / "outside.md").exists()


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
