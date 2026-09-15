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
