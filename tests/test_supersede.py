from datetime import date, timedelta

from adrpy.cli import approve, init, new, supersede
from adrpy.core.errors import CommandError

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


def test_supersede_happy_path(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    successor_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"
    assert result["created"] == str(successor_path)
    assert result["predecessor"] == str(adr_path)
    assert result["status"] == "Proposed"

    predecessor_text = adr_path.read_text(encoding="utf-8")
    assert "|Superseded|Superseded (2026-01-05) : 002|" in predecessor_text

    successor_text = successor_path.read_text(encoding="utf-8")
    # Title comes from the predecessor's FILENAME segment (already
    # case-transformed), not its header's prose title -- confirmed via a
    # real adrplus supersede run (SupersedeCommandHandler uses
    # AdrFileNameComponents.Title, not Header.Title).
    assert "|File title md|use-postgre-sql|" in successor_text
    assert "|Domain|Backend|" in successor_text  # scope/domain inherited
    assert "|Scope|Data|" in successor_text
    assert "|Created|Proposed (2026-01-05)|" in successor_text


def test_supersede_can_override_scope_and_domain(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    supersede.run(["--file", str(adr_path), "--domain", "Platform", "--scope", "Infra"])

    successor_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"
    text = successor_path.read_text(encoding="utf-8")
    assert "|Domain|Platform|" in text
    assert "|Scope|Infra|" in text


def test_supersede_rejects_not_yet_accepted(tmp_path):
    tmp_path = tmp_path
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Still proposed"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-still-proposed.md"

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"


def test_supersede_rejects_already_superseded(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    supersede.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-superseded"


def test_supersede_rejects_refdate_before_accepted_date(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-01"])

    assert excinfo.value.code == "refdate-before-history"


def test_supersede_rejects_refdate_in_future(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", future])

    assert excinfo.value.code == "refdate-in-future"


def test_supersede_rejects_embedded_delimiter_in_scope(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--scope", "Bad|scope"])

    assert excinfo.value.code == "field-contains-forbidden-character"


def test_supersede_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    assert main(["supersede", "--file", str(adr_path)]) == EXIT_SUCCESS
