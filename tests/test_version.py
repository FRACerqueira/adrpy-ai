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
    # Usability audit round 3: the real number was only ever in `detail`
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


def test_version_rejects_when_not_latest_and_latest_not_rejected(tmp_path):
    """Usability audit: not-latest-version must name WHICH version
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


def test_version_rejects_path_traversal_via_header_title(tmp_path):
    """Security audit F1: unlike --title on `new`, version/revise/supersede
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
    """Usability audit A2: --empty is presence-only (confirmed live,
    `--empty true` fails with "Unknown argument") -- must not be declared
    "boolean", which implies accepting an explicit value like
    `config --disableplugins true/false` does."""
    arguments = {argument["name"]: argument for argument in version.describe()["arguments"]}

    assert arguments["empty"]["type"] == "switch"
