from datetime import date, timedelta

from adrpy.cli import approve, init, new, reject, undo
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text

import pytest


def _setup_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    return tmp_path, adr_path


def _write_raw(path, config, **record_kwargs):
    record = DecisionRecord(**record_kwargs)
    atomic_write_text(path, build_header(config, record) + "# body")


# ---- approve ----


def test_approve_happy_path(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    result = approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])

    assert result["status"] == "Accepted"
    text = adr_path.read_text(encoding="utf-8")
    assert "|Changed|Accepted (2026-01-02)|" in text
    assert "|Created|Proposed (2026-01-01)|" in text  # untouched


def test_approve_rejects_already_approved(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "not-eligible-for-approval"


def test_approve_rejects_refdate_before_create(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path), "--refdate", "2025-12-31"])

    assert excinfo.value.code == "refdate-before-history"


def test_approve_rejects_refdate_in_future(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path), "--refdate", future])

    assert excinfo.value.code == "refdate-in-future"


def test_approve_rejects_when_sibling_superseded(tmp_path):
    tmp_path, adr_path = _setup_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    sibling_path = tmp_path / "doc" / "adr" / "ADR001V02-first-decision-v2.md"
    _write_raw(
        sibling_path,
        config,
        number=1,
        title="First decision v2",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 2),
        superseded_by_file="ADR002V01-something.md",  # required: a Superseded row with
        # no ": <file>" suffix is itself unparseable, in the real tool too
    )

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "family-member-superseded"


def test_approve_preserves_exotic_unicode_separators_in_body(tmp_path):
    """Regression for the resilience audit's R1 finding: a body containing
    a Unicode line-separator character that is NOT a real line terminator
    (form feed, NEL, LINE SEPARATOR, ...) must survive a status rewrite
    byte-for-byte. Confirmed live against the real adrplus: none of these
    is treated as a line break there, so the body's line count and content
    are unchanged by `approve`."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    exotic_body = "Body line one.\x0cAfter form-feed.\nNEL here:After NEL.\nLS here: After LS.\n"
    with open(adr_path, "a", encoding="utf-8", newline="") as handle:
        handle.write(exotic_body)
    body_lines_before = adr_path.read_text(encoding="utf-8").count("\n")

    approve.run(["--file", str(adr_path)])

    text_after = adr_path.read_text(encoding="utf-8")
    assert "Body line one.\x0cAfter form-feed." in text_after
    assert "NEL here:After NEL." in text_after
    assert "LS here: After LS." in text_after
    assert text_after.count("\n") == body_lines_before


def test_approve_replaces_invalid_utf8_bytes_in_body_same_as_the_real_tool(tmp_path):
    """Not a bug: confirmed live against the real adrplus (approve on a
    body containing raw invalid UTF-8 bytes) that it ALSO replaces them
    with U+FFFD on rewrite, byte-for-byte identical to this port. Recorded
    as a permanent test so this doesn't get re-investigated as a suspected
    data-loss bug -- tolerating invalid bytes on read (Fase 4) was already
    confirmed fidelity; this confirms the read-then-rewrite round trip is
    too, not an extra liberty this port took on its own."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"\r\nInvalid UTF-8 marker: \xa4\xe9\xe8 end.\r\n")

    approve.run(["--file", str(adr_path)])

    body_bytes = adr_path.read_bytes()
    assert b"\xa4\xe9\xe8" not in body_bytes
    assert "Invalid UTF-8 marker: ��� end.".encode("utf-8") in body_bytes


def test_approve_file_not_found(tmp_path):
    tmp_path, _ = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(tmp_path / "doc" / "adr" / "ADR999V01-missing.md")])

    assert excinfo.value.code == "file-not-found"


# ---- reject ----


def test_reject_happy_path(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    result = reject.run(["--file", str(adr_path), "--refdate", "2026-01-02"])

    assert result["status"] == "Rejected"
    assert result["undone_predecessor"] is None
    text = adr_path.read_text(encoding="utf-8")
    assert "|Changed|Rejected (2026-01-02)|" in text


def test_reject_rejects_already_resolved(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "not-eligible-for-rejection"


def test_reject_undoes_predecessor_supersede_status(tmp_path):
    tmp_path, _ = _setup_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    config = load_repo_config(tmp_path / "adr-config.adrplus")

    predecessor_path = adr_dir / "ADR001V01-first-decision.md"
    _write_raw(
        predecessor_path,
        config,
        number=1,
        title="First decision",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 3),
        superseded_by_file="ADR002V01-successor--001.md",
    )
    successor_path = adr_dir / "ADR002V01-successor--001.md"
    _write_raw(
        successor_path,
        config,
        number=2,
        title="Successor",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 3),
    )

    result = reject.run(["--file", str(successor_path), "--refdate", "2026-01-04"])

    assert result["undone_predecessor"] == str(predecessor_path)
    predecessor_text = predecessor_path.read_text(encoding="utf-8")
    assert "|Superseded||" in predecessor_text


# ---- undo ----


def test_undo_happy_path(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    result = undo.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"
    text = adr_path.read_text(encoding="utf-8")
    assert "|Changed||" in text


def test_undo_rejects_when_still_proposed(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "not-eligible-for-undo"


def test_undo_rejects_when_pending_sibling_exists(tmp_path):
    tmp_path, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    sibling_path = tmp_path / "doc" / "adr" / "ADR001V02-first-decision-v2.md"
    _write_raw(
        sibling_path,
        config,
        number=1,
        title="First decision v2",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 2),
    )

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "family-member-pending"


def test_status_transitions_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    _, adr_path = _setup_repo(tmp_path)

    assert main(["approve", "--file", str(adr_path)]) == EXIT_SUCCESS
    assert main(["undo", "--file", str(adr_path)]) == EXIT_SUCCESS
    assert main(["reject", "--file", str(adr_path)]) == EXIT_SUCCESS
