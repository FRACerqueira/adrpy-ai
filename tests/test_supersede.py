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


def test_supersede_reveals_predecessor_already_superseded_when_successor_write_fails(tmp_path, monkeypatch):
    """Mechanism-correctness audit round 3 (resilience finding #1), the
    worst instance found: supersede marks the predecessor Superseded
    (mark_superseded, a real committed write) BEFORE writing the
    successor. If only the successor write fails with a real OSError, the
    predecessor is left permanently Superseded with no successor ever
    created -- an orphaned, broken family state. The failure response
    must name that partial mutation explicitly via `data`, not just
    convert to the generic io-error the attach_warnings safety net alone
    would produce."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    from adrpy.cli import supersede as supersede_module

    def flaky_write(path, content):
        raise OSError("simulated disk failure")

    monkeypatch.setattr(supersede_module, "atomic_write_text", flaky_write)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "supersede-successor-write-failed"
    assert excinfo.value.data["predecessor"] == str(adr_path)
    assert excinfo.value.data["predecessor_status"] == "Superseded"
    # The predecessor really was mutated on disk despite the overall failure.
    assert "|Superseded|Superseded" in adr_path.read_text(encoding="utf-8")


def test_supersede_reports_the_colliding_filename_as_data_when_it_already_exists(tmp_path, monkeypatch):
    """Simulates the TOCTOU race file-already-exists defends against: a
    concurrent write creates the successor's target filename after this
    call's own scan already took its snapshot (the scan itself would
    otherwise always see any pre-existing file matching the naming scheme
    and bump next_number past it)."""
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    colliding_path = tmp_path / "doc" / "adr" / "ADR002V01-use-postgre-sql--001.md"
    colliding_path.write_text("already here", encoding="utf-8")

    from adrpy.cli import supersede as supersede_module

    real_scan_decisions = supersede_module.scan_decisions

    def scan_without_colliding_file(folder, config, warnings=None):
        return [entry for entry in real_scan_decisions(folder, config) if entry[2].name != colliding_path.name]

    monkeypatch.setattr(supersede_module, "scan_decisions", scan_without_colliding_file)

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "file-already-exists"
    assert excinfo.value.data == {"file": "ADR002V01-use-postgre-sql--001.md"}


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


def test_supersede_does_not_claim_a_rewrite_when_it_fails_before_writing(tmp_path):
    """Round 4 resilience audit, Finding 1, reproduced: encoding_repaired_
    warning claims "the file has been rewritten... bytes are now lost" --
    false whenever the command fails before ever reaching its own write
    (mark_superseded, here blocked by the target still being Proposed)."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Use PostgreSQL"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-use-postgre-sql.md"
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    with pytest.raises(CommandError) as excinfo:
        supersede.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"
    assert not any("rewritten" in w.lower() for w in (excinfo.value.warnings or []))


def test_supersede_claims_the_rewrite_once_it_actually_happens(tmp_path):
    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    result = supersede.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"
    assert any("rewritten" in w.lower() for w in result["warnings"])


def test_supersede_reports_a_retry_warning_when_the_successor_write_needed_several_attempts(
    tmp_path, monkeypatch
):
    """Round 4 test-adequacy audit, Finding 4: retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage.
    supersede.py imports and calls atomic_write_text directly for the
    SUCCESSOR write (unlike the predecessor's own mark_superseded write,
    which goes through core.lifecycle's own reference)."""
    from adrpy.cli import supersede as supersede_module

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)
    real_atomic_write_text = supersede_module.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(supersede_module, "atomic_write_text", flaky_atomic_write_text)

    result = supersede.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_supersede_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    tmp_path, adr_path = _setup_accepted_repo(tmp_path)

    assert main(["supersede", "--file", str(adr_path)]) == EXIT_SUCCESS
