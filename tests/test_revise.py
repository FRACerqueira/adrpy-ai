import json
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
    init.run(["--path", str(tmp_path), "--file", str(config_file)])
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


def test_revise_happy_path(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)

    result = revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    new_path = tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md"
    assert result["created"] == str(new_path)
    text = new_path.read_text(encoding="utf-8")
    assert "|Version|01|" in text  # version unchanged
    assert "|Revision|02|" in text
    assert "|Domain|Backend|" in text  # target's own value
    assert "|Created|Proposed (2026-01-05)|" in text


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
    init.run(["--path", str(tmp_path), "--file", str(config_file)])
    new.run(["--path", str(tmp_path), "--title", "Still proposed"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01R01-still-proposed.md"

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path)])

    assert excinfo.value.code == "not-eligible-for-revision"


def test_revise_rejects_when_not_latest_and_latest_not_rejected(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)
    revise.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    r2_path = tmp_path / "doc" / "adr" / "ADR001V01R02-use-postgre-sql.md"
    approve.run(["--file", str(r2_path), "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        revise.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert excinfo.value.code == "not-latest-version"


def test_revise_branching_from_immediate_predecessor_of_a_rejected_latest_collides(tmp_path):
    """Confirmed against a real `adrplus revise` run: revise's new revision
    number is always TARGET.revision+1 (never latest.revision+1, unlike
    `version`'s always-fresh latest.version+1) -- so branching off the
    revision immediately before a rejected latest recomputes that exact
    same (now-rejected-but-still-on-disk) filename and collides. This is
    the real tool's own behavior, not a bug in this port: the branch-off
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
    """Security audit F1: same class as version's own finding -- revise's
    new record's title also comes straight from the target's already-
    parsed header cell (never delimiter-checked on read)."""
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(_config_with_revisions()), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--file", str(config_file)])
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

    assert excinfo.value.code == "path-outside-repository"
    assert not (tmp_path.parent / "outside.md").exists()


def test_revise_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path, adr_path = _setup_accepted_repo_with_revisions(tmp_path)

    assert main(["revise", "--file", str(adr_path)]) == EXIT_SUCCESS


def test_revise_describe_documents_the_lenrevision_precondition():
    """Usability audit A9: revise fails with revision-not-configured on
    any freshly-init'd repository (100% of the time, not an edge case) --
    describe() never said so, so an agent only discovered this by trial
    and error."""
    assert "lenrevision" in revise.describe()["description"]
