from datetime import date, timedelta

from adrpy.cli import approve, init, new, reject, version
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


def test_version_rejects_when_not_accepted_or_rejected(tmp_path):
    tmp_path = tmp_path
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Still proposed"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-still-proposed.md"

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path)])

    assert excinfo.value.code == "not-eligible-for-version"


def test_version_rejects_when_not_latest_and_latest_not_rejected(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    version.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    v2_path = tmp_path / "doc" / "adr" / "ADR001V02-use-postgre-sql.md"
    approve.run(["--file", str(v2_path), "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        version.run(["--file", str(adr_path), "--refdate", "2026-01-07"])

    assert excinfo.value.code == "not-latest-version"


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
