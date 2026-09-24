import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from adrpy.__main__ import main
from adrpy.cli import approve, config, init, new, reject, supersede, undo, version
from adrpy.core.config import load_repo_config
from adrpy.core.errors import CommandError
from adrpy.core.header import DecisionRecord, build_header
from adrpy.core.atomic_write import atomic_write_text

import pytest

FIXTURE_PATH = "tests/fixtures/adr-config.adrplus"



def _fail_nth_reject_commit(monkeypatch, n):
    """Fails the n-th commit of reject's two prepared writes: 1 is the
    predecessor's revert, 2 this decision's own status."""
    from adrpy.core import lifecycle

    real_commit = lifecycle.commit_write
    calls = {"n": 0}

    def failing_commit(prepared, exclusive=False):
        calls["n"] += 1
        if calls["n"] == n:
            raise OSError("simulated disk failure")
        return real_commit(prepared, exclusive=exclusive)

    monkeypatch.setattr(lifecycle, "commit_write", failing_commit)

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
    assert "|Changed|Accepted (2026-01-02) <!-- Accepted -->|" in text
    assert "|Created|Proposed (2026-01-01) <!-- Proposed -->|" in text  # untouched


def test_approve_rejects_a_hostile_title_found_only_on_rewrite(tmp_path):
    """approve (unlike version/revise/supersede/migrate)
    must re-validate header.title/scope/domain before reusing them in
    its own rewrite -- inert only because _extract_cell structurally
    prevents an embedded '|' or real newline from ever reaching a parsed
    header value, but a colon (a genuine NTFS Alternate-Data-Stream
    separator, not blocked by parse_header's own extraction) survives
    untouched. A hand-edited file's title, never touched by any
    validation until this write, would otherwise embed it into the
    rewritten header with no error at all."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    _write_raw(adr_path, config, number=1, title="Hostile:Title", version=1, status_create="Proposed")

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")


def test_approve_reports_a_marker_label_mismatch_warning(tmp_path):
    """ADR004V01: end-to-end through a real write command (approve is
    representative of all 6 -- read_target's own warning is shared code),
    not just core/header.py's own unit test for this scenario. A hand-
    edited visible label that disagrees with the hidden marker must
    surface as a warning, but must NOT block approve -- the marker is
    still authoritative and the write still proceeds normally."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    text = adr_path.read_text(encoding="utf-8")
    assert f"{config.statusnew} (2026-01-01) <!-- Proposed -->" in text
    atomic_write_text(adr_path, text.replace(config.statusnew, config.statusacc, 1))

    result = approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])

    assert result["status"] == "Accepted"  # the write still proceeds
    assert any("status_create" in w and "marker" in w for w in result["warnings"])


def test_approve_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """Decision log claims approve/reject/undo/version/revise "inherit [the
    family_members fail-closed fix] for free" from family_members' own
    strict=True -- but nothing end-to-end proved that for THIS command.
    Demonstrated: wrapping this command's own family_members call in
    try/except CommandError (a plausible future "degrade gracefully"
    refactor) left the full suite green with no test noticing."""
    tmp_path, adr_path = _setup_repo(tmp_path)
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
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]
    # unchanged, no write made
    assert "|Created|Proposed (2026-01-01) <!-- Proposed -->|" in adr_path.read_text(encoding="utf-8")


def test_approve_rejects_already_approved(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-accepted"


def test_approve_rejects_a_corrupted_status_update_end_to_end(tmp_path):
    """Audit A
    hand-edited/corrupted file whose "Changed" cell holds the "Proposed"
    label text (structurally valid, so header.is_valid stays True) was
    silently accepted by `approve` -- ineligibility_reason_for_approve_or_
    reject fell through to eligible for any status_update other than
    exactly "Accepted"/"Rejected", instead of requiring None."""
    _, adr_path = _setup_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    lines = adr_path.read_text(encoding="utf-8").splitlines()
    lines[9] = lines[9].replace("|Changed||", f"|Changed|{config.statusnew} (2026-01-02)|")
    atomic_write_text(adr_path, "\n".join(lines) + "\n")

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["invalid-status-combination"]
    # And the file must not have been silently overwritten to Accepted.
    assert "|Changed|Accepted" not in adr_path.read_text(encoding="utf-8")


def test_approve_does_not_claim_a_rewrite_when_it_fails_before_writing(tmp_path):
    """encoding_repaired_
    warning claims "the file has been rewritten... bytes are now lost" --
    false whenever the command fails before ever reaching its own write.
    Confirmed live: approve on an already-Accepted, encoding-corrupted
    file must not report this claim, since the file is never touched by
    such a call."""
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-accepted"
    assert not any("rewritten" in w.lower() for w in (excinfo.value.warnings or []))


def test_approve_claims_the_rewrite_once_it_actually_happens(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    result = approve.run(["--file", str(adr_path)])

    assert result["status"] == "Accepted"
    assert any("rewritten" in w.lower() for w in result["warnings"])


def test_approve_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage
    proving it actually reaches a command's own result (only approve.py's
    encoding-repair warning, and new.py's happy path, were ever checked
    for warnings content at all). approve/reject/undo write through
    core.lifecycle.rewrite_status_field, which calls atomic_write_chunks
    (ADR006V01) from ITS OWN module namespace -- patching approve.py's own
    (absent) reference would silently no-op."""
    from adrpy.core import lifecycle

    _, adr_path = _setup_repo(tmp_path)
    real_atomic_write_chunks = lifecycle.atomic_write_chunks

    def flaky_atomic_write_chunks(*args, **kwargs):
        real_atomic_write_chunks(*args, **kwargs)
        return 3

    monkeypatch.setattr(lifecycle, "atomic_write_chunks", flaky_atomic_write_chunks)

    result = approve.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_approve_reports_warnings_when_a_core_helper_raises(tmp_path):
    """Class-closure check (advisor-caught gap): the fix above only threaded
    `warnings` through raise sites living directly in the 8 command files.
    The same invariant is violated just as easily by a CommandError raised
    from a shared core/ helper (here, validate_refdate_not_before, called
    from approve.py) while `warnings` already has entries in scope --
    textually unrelated to the sites already patched, but the same bug.

    Uses an orphaned temp-file
    cleanup instead of an encoding-repair warning for the same reason as
    the test above -- refdate-before-history also fails before any write."""
    _, adr_path = _setup_repo(tmp_path)  # created with refdate 2026-01-01
    orphan_path = adr_path.parent / "orphan.md.0123456789abcdef0123456789abcdef.tmp"
    orphan_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 999
    os.utime(orphan_path, (old_time, old_time))

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path), "--refdate", "2025-12-31"])

    assert excinfo.value.code == "refdate-before-history"
    assert excinfo.value.warnings
    assert any("orphaned" in w.lower() for w in excinfo.value.warnings)


def test_accumulated_warnings_reach_the_real_stdout_json_envelope_on_failure(tmp_path, capsys):
    """End-to-end closure of the same class, through the actual CLI entry
    point rather than the CommandError object directly -- proves the
    warnings genuinely reach the JSON an external caller would parse, not
    just the in-process exception attribute."""
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    orphan_path = adr_path.parent / "orphan.md.0123456789abcdef0123456789abcdef.tmp"
    orphan_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 999
    os.utime(orphan_path, (old_time, old_time))
    capsys.readouterr()  # discard output from the two setup calls above

    exit_code = main(["approve", "--file", str(adr_path)])

    payload = json.loads(capsys.readouterr().out)
    assert exit_code != 0
    assert payload["code"] == "already-accepted"
    assert any("orphaned" in w.lower() for w in payload["warnings"])


def test_reject_reveals_no_write_was_made_when_predecessor_is_missing(tmp_path):
    """Round 36 retraction: an earlier version of this command wrote this
    decision's own status FIRST, so a missing predecessor still reported a
    successful mutation despite the overall failure. The predecessor
    lookup now runs BEFORE any write -- and a successor with no
    predecessor pointing at it is a broken repository rule
    (successor-without-predecessor): nothing is committed at all."""
    target = tmp_path
    init.run(["--path", str(target)])
    config = load_repo_config(target / "adr-config.adrplus")
    adr_dir = target / "doc" / "adr"
    # A real successor shape (its number is higher than the one it names),
    # whose predecessor file does not exist.
    successor_path = adr_dir / "ADR005V01-successor--003.md"
    _write_raw(
        successor_path,
        config,
        number=5,
        title="Successor",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        superseded=3,
    )

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path)])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["successor-without-predecessor"]
    assert "|Changed|Rejected" not in successor_path.read_text(encoding="utf-8")


def test_reject_reports_two_warnings_together_in_order_before_an_unrelated_failure(tmp_path, monkeypatch):
    """No existing test had more than one
    warning accumulated simultaneously before a later failure -- which
    quietly weakens every `assert excinfo.value.warnings` check elsewhere
    (they'd still pass even with a duplicated warning or the wrong
    order). This combines two distinct real side effects (an orphaned
    temp-file cleanup AND an encoding repair) surviving together to a
    later, unrelated CommandError, and checks both content and order.

    Round 36 retraction: previously this used the predecessor-missing
    scenario, since the target's own write ran first and its encoding
    repair was already real by the time that later, unrelated failure hit.
    With the predecessor reverted FIRST now, that specific scenario has no
    write before the failure at all -- so this uses the predecessor's OWN
    encoding repair (real once ITS write succeeds) followed by the
    target's own write failing as the later, unrelated failure instead."""
    from adrpy.cli import supersede

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    successor_path = Path(result["created"])
    # Injected AFTER supersede, directly onto the now-Superseded
    # predecessor -- approve/supersede's own writes would otherwise have
    # already repaired it before reject ever sees it.
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    adr_dir = tmp_path / "doc" / "adr"
    orphan_path = adr_dir / "orphan.md.0123456789abcdef0123456789abcdef.tmp"
    orphan_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 999
    os.utime(orphan_path, (old_time, old_time))

    from adrpy.cli import reject as reject_module

    _fail_nth_reject_commit(monkeypatch, 2)

    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path)])

    assert excinfo.value.code == "multi-file-write-partially-applied"
    assert "mark this decision Rejected by hand" in excinfo.value.detail
    assert len(excinfo.value.warnings) == 2
    assert "orphaned" in excinfo.value.warnings[0].lower()
    assert "rewritten" in excinfo.value.warnings[1].lower()


def test_reject_reveals_predecessor_already_reverted_when_its_own_write_fails(tmp_path, monkeypatch):
    """Round 36 retraction: with the predecessor reverted FIRST now, a
    failure on the SECOND rewrite_status_field call hits this decision's
    OWN write, AFTER the predecessor has already, for real, been reverted
    -- the inverse of the old order's partial-success shape."""
    from adrpy.cli import supersede

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    successor_path = Path(result["created"])

    from adrpy.cli import reject as reject_module

    _fail_nth_reject_commit(monkeypatch, 2)

    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path)])

    assert excinfo.value.code == "multi-file-write-partially-applied"
    assert {k: v for k, v in excinfo.value.data.items() if k != "repair"} == {"applied": [str(adr_path)], "pending": [str(successor_path)]}
    assert set(excinfo.value.data["repair"]) == {"file", "row"}
    assert "|Superseded||" in adr_path.read_text(encoding="utf-8")  # predecessor genuinely reverted
    assert "|Changed|Rejected" not in successor_path.read_text(encoding="utf-8")  # successor NOT written


def test_reject_predecessor_write_itself_fails_with_no_write_made(tmp_path, monkeypatch):
    """Round 36: a failure on the FIRST rewrite_status_field call now hits
    the predecessor's own write, before this decision's own write has
    even been attempted -- nothing committed at all, unlike the old
    order's second-write failure (covered by the sibling tests above,
    which now hit this decision's own write instead)."""
    from adrpy.cli import supersede

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    successor_path = Path(result["created"])
    predecessor_text_before = adr_path.read_text(encoding="utf-8")

    from adrpy.cli import reject as reject_module

    _fail_nth_reject_commit(monkeypatch, 1)

    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path)])

    assert excinfo.value.code == "reject-predecessor-write-failed"
    assert excinfo.value.data is None
    assert adr_path.read_text(encoding="utf-8") == predecessor_text_before  # untouched
    assert "|Changed|Rejected" not in successor_path.read_text(encoding="utf-8")  # successor NOT written


def test_a_retry_after_a_partial_reject_is_refused_until_repaired(tmp_path, monkeypatch):
    """The predecessor was reverted, then this decision's own write
    failed: the successor is left with no predecessor pointing at it
    (successor-without-predecessor), so a retry is refused with nothing
    written; the repair is by hand (mark it Rejected)."""
    from adrpy.cli import supersede

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    successor_path = Path(result["created"])

    from adrpy.cli import reject as reject_module

    _fail_nth_reject_commit(monkeypatch, 2)
    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path), "--refdate", "2026-01-06"])
    assert excinfo.value.code == "multi-file-write-partially-applied"

    monkeypatch.undo()
    before = successor_path.read_bytes()
    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [(e["code"], e["file"]) for e in excinfo.value.data["errors"]] == [
        ("successor-without-predecessor", str(successor_path.resolve()))
    ]
    assert "by hand" in excinfo.value.data["errors"][0]["hint"].lower()
    assert successor_path.read_bytes() == before


def test_following_a_partial_rejects_repair_literally_leaves_a_consistent_repository(tmp_path, monkeypatch):
    from adrpy.cli import reject as reject_module
    from adrpy.cli import supersede
    from adrpy.core.config import load_repo_config
    from adrpy.core.consistency import check_repository

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    successor_path = Path(supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])["created"])
    _fail_nth_reject_commit(monkeypatch, 2)
    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path), "--refdate", "2026-01-06"])
    monkeypatch.undo()

    repair = excinfo.value.data["repair"]
    assert repair["file"] == str(successor_path)
    assert repair["row"] in excinfo.value.detail
    label = repair["row"].split("|")[1]
    lines = successor_path.read_text(encoding="utf-8").split("\n")
    successor_path.write_text(
        "\n".join(repair["row"] if line.startswith(f"|{label}|") else line for line in lines), encoding="utf-8"
    )

    config = load_repo_config(tmp_path / "adr-config.adrplus")
    assert check_repository(adr_path.parent, config)[1] == []


def test_approve_rejects_refdate_before_create(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path), "--refdate", "2025-12-31"])

    assert excinfo.value.code == "refdate-before-history"
    # The real "nothing accumulated" value a
    # command ever produces is `[]` (every command initializes `warnings
    # = []` before any raise site), never `None` -- confirms
    # attach_warnings' merge produces that exact value here, not just
    # something falsy.
    assert excinfo.value.warnings == []


def test_approve_rejects_refdate_in_future(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    future = (date.today() + timedelta(days=1)).isoformat()

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path), "--refdate", future])

    assert excinfo.value.code == "refdate-in-future"


def test_approve_preserves_exotic_unicode_separators_in_body(tmp_path):
    """A body containing
    a Unicode line-separator character that is NOT a real line terminator
    (form feed, NEL, LINE SEPARATOR, ...) must survive a status rewrite
    byte-for-byte. Confirmed live against the reference tool: none of these
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
    """Not a bug: confirmed live against the reference tool (approve on a
    body containing raw invalid UTF-8 bytes) that it ALSO replaces them
    with U+FFFD on rewrite, byte-for-byte identical to this port. Recorded
    as a permanent test so this doesn't get re-investigated as a suspected
    data-loss bug -- tolerating invalid bytes on read Was already
    confirmed fidelity; this confirms the read-then-rewrite round trip is
    too, not an extra liberty this port took on its own."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"\r\nInvalid UTF-8 marker: \xa4\xe9\xe8 end.\r\n")

    result = approve.run(["--file", str(adr_path)])

    body_bytes = adr_path.read_bytes()
    assert b"\xa4\xe9\xe8" not in body_bytes
    assert "Invalid UTF-8 marker: ��� end.".encode("utf-8") in body_bytes
    # load_target's own encoding_repaired
    # report (test_lifecycle.py) must actually reach a real command's
    # result, not just the lifecycle module in isolation.
    assert any("invalid utf-8" in warning.lower() for warning in result["warnings"])


def test_approve_file_not_found(tmp_path):
    tmp_path, _ = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(tmp_path / "doc" / "adr" / "ADR999V01-missing.md")])

    assert excinfo.value.code == "file-not-found"


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_approve_and_reject_refuse_a_placeholder_whose_sibling_was_superseded(tmp_path, command):
    """family-member-superseded on approve/reject, reached with tool
    commands only: two migrated placeholders (V01, V02), V02 superseded
    straight from the placeholder. A Proposed decision never coexists with
    a live Superseded one, but a placeholder is not Proposed."""
    from adrpy.cli import migrate

    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data.update(lenrevision=2, migrationpattern="N00:04T08V04:02R06:02")
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    adr_dir = tmp_path / "doc" / "adr"
    adr_dir.mkdir(parents=True, exist_ok=True)
    v01, v02 = adr_dir / "00010101Foo.md", adr_dir / "00010201Foo.md"
    for path in (v01, v02):
        path.write_bytes(b"# Foo\n\nbody\n")
    migrate.run(["--path", str(tmp_path)])
    supersede.run(["--file", str(v02), "--refdate", "2026-01-05"])
    before = v01.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        (approve if command == "approve" else reject).run(["--file", str(v01), "--refdate", "2026-01-06"])

    assert excinfo.value.code == "family-member-superseded"
    assert excinfo.value.data["superseded_file"] == str(v02.resolve())
    assert v01.read_bytes() == before


# ---- reject ----


def test_reject_happy_path(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    result = reject.run(["--file", str(adr_path), "--refdate", "2026-01-02"])

    assert result["status"] == "Rejected"
    assert result["undone_predecessor"] is None
    text = adr_path.read_text(encoding="utf-8")
    assert "|Changed|Rejected (2026-01-02) <!-- Rejected -->|" in text


def test_reject_rejects_a_hostile_title_found_only_on_rewrite(tmp_path):
    """See approve's own equivalent test -- reject shares the same gap."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    _write_raw(adr_path, config, number=1, title="Hostile:Title", version=1, status_create="Proposed")

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")


def test_reject_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """See approve's own
    equivalent test -- this is reject's OWN family scan (its own family,
    not the predecessor lookup covered above), which runs before any write."""
    tmp_path, adr_path = _setup_repo(tmp_path)
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
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]
    # unchanged, no write made
    assert "|Created|Proposed (2026-01-01) <!-- Proposed -->|" in adr_path.read_text(encoding="utf-8")


def test_reject_rejects_already_resolved(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-accepted"


def test_reject_does_not_claim_a_rewrite_when_it_fails_before_writing(tmp_path):
    """Same class as
    approve's own test."""
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-accepted"
    assert not any("rewritten" in w.lower() for w in (excinfo.value.warnings or []))


def test_reject_claims_the_rewrite_once_it_actually_happens(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    result = reject.run(["--file", str(adr_path)])

    assert result["status"] == "Rejected"
    assert any("rewritten" in w.lower() for w in result["warnings"])


def test_reject_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """Same class as approve's
    own test."""
    from adrpy.core import lifecycle

    _, adr_path = _setup_repo(tmp_path)
    real_atomic_write_chunks = lifecycle.atomic_write_chunks

    def flaky_atomic_write_chunks(*args, **kwargs):
        real_atomic_write_chunks(*args, **kwargs)
        return 3

    monkeypatch.setattr(lifecycle, "atomic_write_chunks", flaky_atomic_write_chunks)

    result = reject.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_reject_claims_the_predecessor_rewrite_only_once_it_actually_happens(tmp_path):
    """Same class as the target's own fix above, for reject's SECOND write
    (undoing the predecessor's Superseded status)."""
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
        superseded_by_file="002",  # bare zero-padded number (lenseq=3), not a filename -- see prepare_mark_superseded's docstring
    )
    with open(predecessor_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")
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
    assert any("rewritten" in w.lower() and str(predecessor_path) in w for w in result["warnings"])


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
        superseded_by_file="002",  # bare zero-padded number (lenseq=3), not a filename -- see prepare_mark_superseded's docstring
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


def test_reject_reverts_the_correct_predecessor_not_just_the_latest_family_member(tmp_path):
    """Reject picks the predecessor to revert by the member whose
    Superseded cell names this successor, not the family's latest member
    (highest version/revision). Reached with tool commands only: V02 was
    rejected, which left V01 live, and V01 -- not the latest member -- was
    superseded."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    v02_path = Path(version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"])
    reject.run(["--file", str(v02_path), "--refdate", "2026-01-03"])
    successor_path = Path(supersede.run(["--file", str(adr_path), "--refdate", "2026-01-04"])["created"])
    v02_before = v02_path.read_bytes()

    result = reject.run(["--file", str(successor_path), "--refdate", "2026-01-05"])

    assert result["undone_predecessor"] == str(adr_path.resolve())
    assert "|Superseded||" in adr_path.read_text(encoding="utf-8"), "V01 (the real predecessor) should have been un-superseded"
    assert v02_path.read_bytes() == v02_before, "V02 was never superseded and must stay untouched"


# ---- undo ----


def test_undo_happy_path(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    result = undo.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"
    text = adr_path.read_text(encoding="utf-8")
    assert "|Changed||" in text


def test_undo_rejects_a_hostile_title_found_only_on_rewrite(tmp_path):
    """See approve's own equivalent test -- undo shares the same gap."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    config = load_repo_config(tmp_path / "adr-config.adrplus")
    _write_raw(
        adr_path, config, number=1, title="Hostile:Title", version=1,
        status_create="Proposed", status_update="Accepted", date_update=date(2026, 1, 2),
    )

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert error["code"] == "invalid-header"
    assert error["detail"].startswith("field-contains-forbidden-character")


def test_undo_fails_closed_when_a_subdirectory_is_unreadable(tmp_path, monkeypatch):
    """See approve's own
    equivalent test."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
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
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    assert [error["code"] for error in excinfo.value.data["errors"]] == ["scan-incomplete"]
    assert "|Changed|Accepted" in adr_path.read_text(encoding="utf-8")  # unchanged, no write made


def test_undo_does_not_claim_a_rewrite_when_it_fails_before_writing(tmp_path):
    """Same class as
    approve's own test."""
    _, adr_path = _setup_repo(tmp_path)
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])  # still Proposed -- nothing to undo

    assert excinfo.value.code == "still-proposed"
    assert not any("rewritten" in w.lower() for w in (excinfo.value.warnings or []))


def test_undo_claims_the_rewrite_once_it_actually_happens(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
    with open(adr_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    result = undo.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"
    assert any("rewritten" in w.lower() for w in result["warnings"])


def test_undo_reports_a_retry_warning_when_the_write_needed_several_attempts(tmp_path, monkeypatch):
    """Same class as approve's
    own test."""
    from adrpy.core import lifecycle

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
    real_atomic_write_chunks = lifecycle.atomic_write_chunks

    def flaky_atomic_write_chunks(*args, **kwargs):
        real_atomic_write_chunks(*args, **kwargs)
        return 3

    monkeypatch.setattr(lifecycle, "atomic_write_chunks", flaky_atomic_write_chunks)

    result = undo.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_undo_scans_the_directory_only_once(tmp_path, monkeypatch):
    """The repository is read once per call: one scan of the decisions
    folder (core/consistency), whose snapshot feeds the target, its family
    and every guard -- no second scan."""
    from adrpy.core import consistency, lifecycle

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    calls = []
    original = consistency.scan_tree

    def counting_scan_tree(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(consistency, "scan_tree", counting_scan_tree)
    monkeypatch.setattr(lifecycle, "scan_tree", counting_scan_tree)

    undo.run(["--file", str(adr_path)])

    assert len(calls) == 1


def test_undo_rejects_when_still_proposed(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"


def test_undo_rejects_when_sibling_superseded(tmp_path):
    """family-member-superseded, reached with tool commands only: V02 was
    rejected, which left V01 live, and V01 was then superseded. Undoing
    V02's Rejected status would bring a second live line back."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    v02 = version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    reject.run(["--file", v02, "--refdate", "2026-01-03"])
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-04"])
    before = Path(v02).read_bytes()

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", v02])

    assert excinfo.value.code == "family-member-superseded"
    assert excinfo.value.data["superseded_file"] == str(adr_path.resolve())
    assert Path(v02).read_bytes() == before


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


def test_undo_refuses_a_repository_with_an_unmigrated_legacy_file(tmp_path):
    """A hand-written, never-migrated legacy file (matched by
    migrationpattern "N00:04T04") has an ADR name and no header: a broken
    repository rule (no-header, with the migrate hint), so undo refuses
    with nothing written. (It used to be left out of the family and
    ignored.)"""
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["migrationpattern"] = "N00:04T04"
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])

    legacy_sibling = tmp_path / "doc" / "adr" / "0001LegacyNotes.md"
    legacy_sibling.write_text("# Some legacy notes\n\nNever run through migrate.\n", encoding="utf-8")
    before = adr_path.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "repository-inconsistent"
    [error] = excinfo.value.data["errors"]
    assert (error["code"], error["file"]) == ("no-header", str(legacy_sibling.resolve()))
    assert "migrate" in error["hint"]
    assert adr_path.read_bytes() == before


def test_status_transitions_end_to_end_through_main(tmp_path):
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    _, adr_path = _setup_repo(tmp_path)

    assert main(["approve", "--file", str(adr_path)]) == EXIT_SUCCESS
    assert main(["undo", "--file", str(adr_path)]) == EXIT_SUCCESS
    assert main(["reject", "--file", str(adr_path)]) == EXIT_SUCCESS


def test_approve_accepts_short_flags_end_to_end_through_main(tmp_path):
    """The reference tool's -f/-r; end-to-end through
    main(), not just parse_flags in isolation."""
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    _, adr_path = _setup_repo(tmp_path)

    assert main(["approve", "-f", str(adr_path), "-r", "2026-01-02"]) == EXIT_SUCCESS
    assert "|Changed|Accepted (2026-01-02) <!-- Accepted -->|" in adr_path.read_text(encoding="utf-8")


@pytest.mark.parametrize("boms", [1, 2])
def test_a_decision_an_editor_saved_with_a_bom_is_still_read(tmp_path, boms):
    # PowerShell 5.1 (-Encoding UTF8) and some editors prepend a BOM; the
    # tool never writes one, so it is not content. The rewrite drops it.
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First", "--refdate", "2026-01-01"])
    path = tmp_path / "doc" / "adr" / "ADR001V01-first.md"
    path.write_bytes(b"\xef\xbb\xbf" * boms + path.read_bytes())

    result = approve.run(["--file", str(path), "--refdate", "2026-01-02"])

    assert result["status"] == "Accepted"
    assert path.read_text(encoding="utf-8").startswith("<!-- ")



# ---- Round 40: only the family's latest member is alive ----


def _family_with_v02(tmp_path, v02_status):
    """V01 Accepted, then V02 created from it and moved to `v02_status`."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First", "--refdate", "2026-01-01"])
    adr = tmp_path / "doc" / "adr"
    v01 = adr / "ADR001V01-first.md"
    approve.run(["--file", str(v01), "--refdate", "2026-01-02"])
    v02 = Path(version.run(["--file", str(v01), "--refdate", "2026-01-03"])["created"])
    if v02_status == "Accepted":
        approve.run(["--file", str(v02), "--refdate", "2026-01-04"])
    elif v02_status == "Rejected":
        reject.run(["--file", str(v02), "--refdate", "2026-01-04"])
    return adr, v01, v02


@pytest.mark.parametrize("command", ["undo", "supersede"])
def test_a_version_is_locked_once_a_newer_version_is_alive(tmp_path, command):
    adr, v01, v02 = _family_with_v02(tmp_path, "Accepted")
    before = v01.read_text(encoding="utf-8")
    args = ["--file", str(v01)] + ([] if command == "undo" else ["--refdate", "2026-01-05"])

    with pytest.raises(CommandError) as excinfo:
        {"undo": undo, "supersede": supersede}[command].run(args)

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == str(v02)
    assert v01.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in adr.glob("*.md")) == [v01.name, v02.name]


def test_a_single_rejected_newer_version_leaves_the_older_one_alive(tmp_path):
    adr, v01, v02 = _family_with_v02(tmp_path, "Rejected")

    result = undo.run(["--file", str(v01)])

    assert result["status"] == "Proposed"


def test_rejected_newer_versions_never_lock_the_older_one(tmp_path):
    # Round 41 (H1a): rejected attempts never lock what came before them --
    # with every newer version Rejected, the Accepted V01 is still alive.
    adr, v01, v02 = _family_with_v02(tmp_path, "Rejected")
    v03 = Path(version.run(["--file", str(v01), "--refdate", "2026-01-05"])["created"])
    reject.run(["--file", str(v03), "--refdate", "2026-01-06"])

    assert undo.run(["--file", str(v01)])["status"] == "Proposed"


def test_a_newer_version_that_is_not_rejected_still_locks_the_older_one(tmp_path):
    # Positive control for the rule above: one live newer member is enough.
    adr, v01, v02 = _family_with_v02(tmp_path, "Rejected")
    v03 = Path(version.run(["--file", str(v01), "--refdate", "2026-01-05"])["created"])
    approve.run(["--file", str(v03), "--refdate", "2026-01-06"])

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(v01)])

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == str(v03)


def test_family_refusals_name_the_file_to_act_on(tmp_path):
    # Round 41 (H5a): the refusal says which member is in the way.
    adr, v01, v02 = _family_with_v02(tmp_path, "Proposed")
    with pytest.raises(CommandError) as pending:
        supersede.run(["--file", str(v01), "--refdate", "2026-01-05"])
    assert pending.value.code == "family-member-pending"
    assert pending.value.data["pending_file"] == str(v02)

    approve.run(["--file", str(v02), "--refdate", "2026-01-05"])
    succ = Path(supersede.run(["--file", str(v02), "--refdate", "2026-01-06"])["created"])
    with pytest.raises(CommandError) as frozen:
        undo.run(["--file", str(v01)])
    assert frozen.value.code == "family-member-superseded"
    assert frozen.value.data["superseded_file"] == str(v02)

    reject.run(["--file", str(succ), "--refdate", "2026-01-07"])
    with pytest.raises(CommandError) as final:
        undo.run(["--file", str(succ)])
    assert final.value.code == "rejected-successor-is-final"
    assert final.value.data == {"successor_file": str(succ), "predecessor_number": 1}


def _rejected_successor(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First", "--refdate", "2026-01-01"])
    adr = tmp_path / "doc" / "adr"
    pred = adr / "ADR001V01-first.md"
    approve.run(["--file", str(pred), "--refdate", "2026-01-02"])
    succ = Path(supersede.run(["--file", str(pred), "--refdate", "2026-01-03"])["created"])
    reject.run(["--file", str(succ), "--refdate", "2026-01-04"])
    return adr, pred, succ


@pytest.mark.parametrize("command", ["undo", "version"])
def test_a_rejected_successor_is_final(tmp_path, command):
    # A rejected successor is the end of its line: its predecessor was put
    # back, and nothing may bring the successor back to life or branch off it.
    adr, pred, succ = _rejected_successor(tmp_path)
    before = succ.read_text(encoding="utf-8")
    args = ["--file", str(succ)] + ([] if command == "undo" else ["--refdate", "2026-01-05"])

    with pytest.raises(CommandError) as excinfo:
        {"undo": undo, "version": version}[command].run(args)

    assert excinfo.value.code == "rejected-successor-is-final"
    assert succ.read_text(encoding="utf-8") == before
    assert sorted(p.name for p in adr.glob("*.md")) == sorted([pred.name, succ.name])


@pytest.mark.parametrize("command", ["approve", "supersede"])
def test_a_hand_made_member_in_a_rejected_successors_family_refuses_the_repository(tmp_path, command):
    # A Proposed V02 written by hand next to the rejected successor: approve
    # would bring the family back to life, and a new supersede of the
    # predecessor would then leave it two live lines. The validator refuses
    # the whole repository first.
    adr, pred, succ = _rejected_successor(tmp_path)
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")
    v02 = adr / "ADR002V02-first.md"
    _write_raw(v02, cfg, number=2, title="First", version=2, status_create="Proposed", date_create=date(2026, 1, 4))
    target = {"approve": v02, "supersede": pred}[command]
    from adrpy.cli import check

    with pytest.raises(CommandError) as checked:
        check.run(["--path", str(tmp_path)])
    assert [e["code"] for e in checked.value.data["errors"]] == ["rejected-successor-family-not-final"]

    with pytest.raises(CommandError) as excinfo:
        {"approve": approve, "supersede": supersede}[command].run(["--file", str(target), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "repository-inconsistent"
    assert [(e["code"], e["file"]) for e in excinfo.value.data["errors"]] == [
        ("rejected-successor-family-not-final", str(v02.resolve()))
    ]
    assert sorted(p.name for p in adr.glob("*.md")) == sorted([pred.name, succ.name, v02.name])


def test_a_rejected_decision_that_is_not_a_successor_can_still_be_undone(tmp_path):
    # Positive control: only a successor (name carrying --NNN) is final.
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First", "--refdate", "2026-01-01"])
    path = tmp_path / "doc" / "adr" / "ADR001V01-first.md"
    reject.run(["--file", str(path), "--refdate", "2026-01-02"])

    assert undo.run(["--file", str(path)])["status"] == "Proposed"


def test_reject_still_reverts_the_predecessor_after_lenseq_changes(tmp_path):
    # The Superseded cell stores the successor's number padded to the
    # lenseq in force when it was written; a later lenseq change must not
    # strand the predecessor (compared as a number, not as text).
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First", "--refdate", "2026-01-01"])
    pred = tmp_path / "doc" / "adr" / "ADR001V01-first.md"
    approve.run(["--file", str(pred), "--refdate", "2026-01-02"])
    succ = Path(supersede.run(["--file", str(pred), "--refdate", "2026-01-03"])["created"])
    config.run(["--path", str(tmp_path), "--lenseq", "4"])

    result = reject.run(["--file", str(succ), "--refdate", "2026-01-04"])

    assert result["undone_predecessor"] == str(pred)
    assert "|Superseded||" in pred.read_text(encoding="utf-8")



def test_a_superseded_sibling_saved_with_a_bom_still_freezes_the_family(tmp_path):
    # The BOM strip also applies to the family's members, not only to the
    # target: V01 (Superseded, reached with tool commands only) saved with a
    # BOM still blocks undoing the rejected V02.
    tmp_path, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    v02 = version.run(["--file", str(adr_path), "--refdate", "2026-01-03"])["created"]
    reject.run(["--file", v02, "--refdate", "2026-01-03"])
    supersede.run(["--file", str(adr_path), "--refdate", "2026-01-04"])
    adr_path.write_bytes(b"\xef\xbb\xbf" + adr_path.read_bytes())

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", v02])

    assert excinfo.value.code == "family-member-superseded"


def test_the_whole_family_of_a_rejected_successor_is_final(tmp_path):
    # A version of a successor carries no --NNN suffix; it is the
    # successor's family all the same, so once the successor is rejected
    # none of it comes back to life (it would give the predecessor a
    # second live line after a new supersede).
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First", "--refdate", "2026-01-01"])
    adr = tmp_path / "doc" / "adr"
    pred = adr / "ADR001V01-first.md"
    approve.run(["--file", str(pred), "--refdate", "2026-01-02"])
    succ = Path(supersede.run(["--file", str(pred), "--refdate", "2026-01-03"])["created"])
    approve.run(["--file", str(succ), "--refdate", "2026-01-04"])
    v02 = Path(version.run(["--file", str(succ), "--refdate", "2026-01-05"])["created"])
    reject.run(["--file", str(v02), "--refdate", "2026-01-06"])
    undo.run(["--file", str(succ)])
    reject.run(["--file", str(succ), "--refdate", "2026-01-07"])
    assert "|Superseded||" in pred.read_text(encoding="utf-8")

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(v02)])

    assert excinfo.value.code == "rejected-successor-is-final"


def test_reject_treats_a_non_ascii_digit_back_reference_as_not_naming_it(tmp_path):
    tmp_path, _ = _setup_repo(tmp_path)
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"
    pred = adr_dir / "ADR001V01-first-decision.md"
    _write_raw(
        pred, cfg, number=1, title="First decision", version=1,
        status_create="Proposed", date_create=date(2026, 1, 1),
        status_update="Accepted", date_update=date(2026, 1, 1),
        status_change="Superseded", date_change=date(2026, 1, 2), superseded_by_file="002",
    )
    pred.write_text(pred.read_text(encoding="utf-8").replace(": 002|", ": \u00b2|"), encoding="utf-8")
    successor_path = adr_dir / "ADR002V01-successor--001.md"
    _write_raw(
        successor_path, cfg, number=2, title="Successor", version=1,
        status_create="Proposed", date_create=date(2026, 1, 3), superseded=1,
    )

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "repository-inconsistent"



def _migrated_family(tmp_path, *names, pattern="N00:04T06V04:02", lenrevision=0):
    """Legacy files brought in by migrate: placeholders with blank cells."""
    import json as _json
    from adrpy.cli import migrate as migrate_cmd

    config = _json.loads(open("tests/fixtures/adr-config.adrplus", encoding="utf-8").read())
    config.update(migrationpattern=pattern, lenrevision=lenrevision)
    seed = tmp_path / "seed.json"
    seed.write_text(_json.dumps(config), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(seed)])
    adr = tmp_path / config["folderadr"]
    adr.mkdir(parents=True, exist_ok=True)
    for name in names:
        (adr / name).write_bytes(b"# legacy\n\nbody\n")
    migrate_cmd.run(["--path", str(tmp_path)])
    return adr


@pytest.mark.parametrize("command", ["approve", "reject"])
def test_approve_and_reject_refuse_a_locked_migrated_placeholder(tmp_path, command):
    # Placeholders never count as the open Proposed member, so the family
    # lock is the only thing standing between V01 and a second live member.
    adr = _migrated_family(tmp_path, "000101Foo.md", "000102Foo.md")
    v01, v02 = adr / "000101Foo.md", adr / "000102Foo.md"
    before = v01.read_bytes()

    with pytest.raises(CommandError) as excinfo:
        {"approve": approve, "reject": reject}[command].run(["--file", str(v01), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == str(v02)
    assert v01.read_bytes() == before


def test_approve_refuses_a_locked_migrated_revision(tmp_path):
    adr = _migrated_family(tmp_path, "00010101Foo.md", "00010102Foo.md", pattern="N00:04T08V04:02R06:02", lenrevision=2)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr / "00010101Foo.md"), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "not-latest-version"
    assert excinfo.value.data["latest_file"] == str(adr / "00010102Foo.md")


def test_supersede_of_a_member_whose_newer_versions_are_all_rejected_works(tmp_path):
    adr, v01, v02 = _family_with_v02(tmp_path, "Rejected")

    result = supersede.run(["--file", str(v01), "--refdate", "2026-01-05"])

    assert Path(result["created"]).name.endswith("--001.md")


def test_reject_leaves_the_predecessor_alone_for_a_non_ascii_back_reference(tmp_path):
    tmp_path, _ = _setup_repo(tmp_path)
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")
    adr_dir = tmp_path / "doc" / "adr"
    pred = adr_dir / "ADR001V01-first-decision.md"
    _write_raw(
        pred, cfg, number=1, title="First decision", version=1,
        status_create="Proposed", date_create=date(2026, 1, 1),
        status_update="Accepted", date_update=date(2026, 1, 1),
        status_change="Superseded", date_change=date(2026, 1, 2), superseded_by_file="002",
    )
    pred.write_text(pred.read_text(encoding="utf-8").replace(": 002|", ": \u0660\u0660\u0662|"), encoding="utf-8")
    before = pred.read_bytes()
    successor_path = adr_dir / "ADR002V01-successor--001.md"
    _write_raw(
        successor_path, cfg, number=2, title="Successor", version=1,
        status_create="Proposed", date_create=date(2026, 1, 3), superseded=1,
    )

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "repository-inconsistent"
    assert pred.read_bytes() == before


def test_reject_of_a_successor_with_no_predecessor_never_rejects_it_alone(tmp_path, monkeypatch):
    """The validator refuses a live successor no predecessor points back
    at (successor-without-predecessor), so reject's predecessor lookup
    cannot come back empty. With the validator bypassed, the lookup's
    guard fails loudly, naming the file, and nothing is written."""
    from adrpy.core import lifecycle
    from adrpy.core.consistency import check_repository

    from conftest import D, make_repo

    repo = make_repo(tmp_path, files=[D(1, state="accepted"), D(2, state="proposed", suffix=1)])
    monkeypatch.setattr(
        lifecycle, "validate_repository", lambda folder, cfg, scan=None: check_repository(folder, cfg, scan)[0]
    )
    before = [path.read_bytes() for path in repo.paths]

    with pytest.raises(AssertionError, match=repo.paths[1].name):
        reject.run(["--file", str(repo.paths[1])])

    assert [path.read_bytes() for path in repo.paths] == before
