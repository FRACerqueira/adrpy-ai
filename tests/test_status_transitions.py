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


def _setup_repo(tmp_path):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    return tmp_path, adr_path


def _write_raw(path, config, **record_kwargs):
    record = DecisionRecord(**record_kwargs)
    atomic_write_text(path, build_header(config, record) + "# body")


# ---- approve ----


def test_approve_aborts_if_folderadr_changed_after_lock_acquired(tmp_path, monkeypatch):
    """Root cause shared by 8 call sites (representative of the 6
    commands wired through resolve_repo_and_target): approve's own
    pre-lock config read can go
    stale if a concurrent config edit changes folderadr before this
    call's own lock is actually acquired -- it would then lock, and
    operate against, a directory the repository no longer uses.
    Simulates the race by patching resolve_repo_and_target's own return
    to report the stale folderadr while the target file genuinely lives
    under the new one."""
    init.run(["--path", str(tmp_path)])
    stale_config = load_repo_config(tmp_path / "adr-config.adrplus")

    config.run(["--path", str(tmp_path), "--folderadr", "doc/adrB"])
    new.run(["--path", str(tmp_path), "--title", "Live decision"])
    adr_path = tmp_path / "doc" / "adrB" / "ADR001V01-live-decision.md"
    original_content = adr_path.read_text(encoding="utf-8")

    real_resolve = approve.resolve_repo_and_target

    def stale_resolve(fileadr):
        _config, root, path = real_resolve(fileadr)
        return stale_config, root, path

    monkeypatch.setattr(approve, "resolve_repo_and_target", stale_resolve)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "folderadr-changed-after-lock-acquired"
    assert excinfo.value.data == {"locked_folderadr": "doc/adr", "current_folderadr": "doc/adrB"}
    # The live decision under the real, current folder survives untouched.
    assert adr_path.read_text(encoding="utf-8") == original_content


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

    assert excinfo.value.code == "field-contains-forbidden-character"


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

    assert excinfo.value.code == "family-scan-incomplete"
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

    assert excinfo.value.code == "unexpected-status"
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
    orphan_path = adr_path.parent / "orphan.md.abc123.tmp"
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
    orphan_path = adr_path.parent / "orphan.md.abc123.tmp"
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
    lookup now runs BEFORE any write -- a missing predecessor means
    nothing was committed at all, safely retryable from scratch."""
    target = tmp_path
    init.run(["--path", str(target)])
    config = load_repo_config(target / "adr-config.adrplus")
    adr_dir = target / "doc" / "adr"
    successor_path = adr_dir / "ADR002V01-successor--999.md"
    _write_raw(
        successor_path,
        config,
        number=2,
        title="Successor",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        superseded=999,
    )

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path)])

    assert excinfo.value.code == "superseded-predecessor-not-found"
    assert excinfo.value.data is None
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
    orphan_path = adr_dir / "orphan.md.abc123.tmp"
    orphan_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 999
    os.utime(orphan_path, (old_time, old_time))

    from adrpy.cli import reject as reject_module

    real_rewrite = reject_module.rewrite_status_field
    calls = {"n": 0}

    def flaky_rewrite(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        return real_rewrite(*args, **kwargs)

    monkeypatch.setattr(reject_module, "rewrite_status_field", flaky_rewrite)

    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path)])

    assert excinfo.value.code == "reject-own-write-failed-after-predecessor-reverted"
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

    real_rewrite = reject_module.rewrite_status_field
    calls = {"n": 0}

    def flaky_rewrite(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        return real_rewrite(*args, **kwargs)

    monkeypatch.setattr(reject_module, "rewrite_status_field", flaky_rewrite)

    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path)])

    assert excinfo.value.code == "reject-own-write-failed-after-predecessor-reverted"
    assert excinfo.value.data == {"predecessor_file": str(adr_path)}
    assert "|Superseded||" in adr_path.read_text(encoding="utf-8")  # predecessor genuinely reverted
    assert "|Changed|Rejected" not in successor_path.read_text(encoding="utf-8")  # successor NOT written


def test_reject_reveals_predecessor_already_reverted_when_the_lock_is_lost_on_its_own_write(tmp_path, monkeypatch):
    """Same class as the OSError
    sibling test above, but for LockLostError on this command's SECOND
    write. Round 36 retraction: with the predecessor reverted first, the
    lock steal now has to land on the TARGET's own stream (the second
    call), not the predecessor's.

    ADR006V01: the target's own body is streamed directly from disk
    (core/lifecycle.py's stream_normalized_body_chunks) rather than read
    up front -- so the lock steal happens DURING that stream, to land in
    the same check-to-commit window `lock.verify_still_held()` is meant to
    close (see core/lifecycle.py's _rewrite_with_streamed_body, which
    re-verifies the lock a second time right before this exact write
    commits, specifically to keep this window shut now that streaming a
    real body can take non-trivial time)."""
    from adrpy.cli import supersede

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    successor_path = Path(result["created"])

    import adrpy.core.lifecycle as lifecycle_module
    from adrpy.cli import reject as reject_module

    real_stream = lifecycle_module.stream_normalized_body_chunks
    calls = {"n": 0}

    def steal_lock_then_stream(source_path, report):
        calls["n"] += 1
        if calls["n"] == 2:
            # The FIRST call streams the predecessor's own write, which
            # must succeed normally -- only the SECOND call, the target's
            # own write, is where this test steals the lock.
            lock_path = tmp_path / "doc" / "adr" / ".adrpy.lock"
            lock_path.write_text(f"someone-else-entirely\n{time.time()}")
        yield from real_stream(source_path, report)

    monkeypatch.setattr(lifecycle_module, "stream_normalized_body_chunks", steal_lock_then_stream)

    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path)])

    assert excinfo.value.code == "reject-own-write-failed-after-predecessor-reverted"
    assert excinfo.value.data == {"predecessor_file": str(adr_path)}
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

    real_rewrite = reject_module.rewrite_status_field
    calls = {"n": 0}

    def flaky_rewrite(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated disk failure")
        return real_rewrite(*args, **kwargs)

    monkeypatch.setattr(reject_module, "rewrite_status_field", flaky_rewrite)

    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path)])

    assert excinfo.value.code == "reject-predecessor-write-failed"
    assert excinfo.value.data is None
    assert adr_path.read_text(encoding="utf-8") == predecessor_text_before  # untouched
    assert "|Changed|Rejected" not in successor_path.read_text(encoding="utf-8")  # successor NOT written


def test_reject_retries_safely_after_predecessor_already_reverted_single_member_family(tmp_path, monkeypatch):
    """Round 36: the whole point of reverting the predecessor first is
    that the failure above is safely retryable. For a predecessor with no
    version/revision history (the common case), a plain retry recognizes
    the since-reverted predecessor (status_change is None, single family
    member) and completes -- it does not re-attempt the revert and does
    not report superseded-predecessor-not-found."""
    from adrpy.cli import supersede

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-05"])
    successor_path = Path(result["created"])

    from adrpy.cli import reject as reject_module

    real_rewrite = reject_module.rewrite_status_field
    calls = {"n": 0}

    def fail_second_call_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated disk failure")
        return real_rewrite(*args, **kwargs)

    monkeypatch.setattr(reject_module, "rewrite_status_field", fail_second_call_once)
    with pytest.raises(CommandError) as excinfo:
        reject_module.run(["--file", str(successor_path), "--refdate", "2026-01-06"])
    assert excinfo.value.code == "reject-own-write-failed-after-predecessor-reverted"

    monkeypatch.setattr(reject_module, "rewrite_status_field", real_rewrite)
    result = reject_module.run(["--file", str(successor_path), "--refdate", "2026-01-06"])

    assert result["status"] == "Rejected"
    assert result["undone_predecessor"] is None  # nothing left to revert this time
    assert "|Changed|Rejected" in successor_path.read_text(encoding="utf-8")


def test_reject_retry_still_fails_loudly_for_a_multi_member_predecessor_family(tmp_path):
    """Same retry scenario as the single-member test above, but the
    predecessor's family has version history (two members) -- deliberately
    NOT auto-recognized as already reverted, since which specific sibling
    was the reverted one can't be disambiguated once its own back-
    reference is gone. Simulates the already-reverted state directly
    (hand-written via _write_raw, both members already status_change=None
    -- as they would be after a genuine revert, or simply never
    superseded) rather than via an injected write failure, since the
    point here is the detection logic itself, not how the state was
    reached."""
    tmp_path, _ = _setup_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")

    v01_path = adr_dir / "ADR001V01-first-decision.md"
    _write_raw(
        v01_path,
        cfg,
        number=1,
        title="First decision",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 1),
        # Already back to normal -- as it would be after an earlier,
        # partially-failed reject already reverted it for real.
    )
    v02_path = adr_dir / "ADR001V02-first-decision.md"
    _write_raw(
        v02_path,
        cfg,
        number=1,
        title="First decision",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 2),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
    )
    successor_path = adr_dir / "ADR002V01-successor--001.md"
    _write_raw(
        successor_path,
        cfg,
        number=2,
        title="Successor",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 3),
        superseded=1,
    )

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path), "--refdate", "2026-01-05"])

    assert excinfo.value.code == "superseded-predecessor-not-found"
    assert excinfo.value.data is None
    assert "|Changed|Rejected" not in successor_path.read_text(encoding="utf-8")


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
        # no ": <file>" suffix is itself unparseable, in the reference tool too
    )

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "family-member-superseded"


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

    assert excinfo.value.code == "field-contains-forbidden-character"


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

    assert excinfo.value.code == "family-scan-incomplete"
    # unchanged, no write made
    assert "|Created|Proposed (2026-01-01) <!-- Proposed -->|" in adr_path.read_text(encoding="utf-8")


def test_reject_rejects_already_resolved(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-accepted"


def test_reject_rejects_when_sibling_superseded(tmp_path):
    """Family-member-superseded
    is raised by hand at 8 separate call sites across 5 command files;
    only approve's own was tested. reject's own raise site (reject.py)
    had zero coverage."""
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
        superseded_by_file="ADR002V01-something.md",
    )

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "family-member-superseded"


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
        superseded_by_file="002",  # bare zero-padded number (lenseq=3), not a filename -- see mark_superseded's docstring
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
        superseded_by_file="002",  # bare zero-padded number (lenseq=3), not a filename -- see mark_superseded's docstring
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
    """Reject picked the
    predecessor to revert via latest_in_family (highest version/revision)
    instead of matching the family member whose own superseded_by_file
    actually names this successor. Reachable without any concurrency and
    without the back-reference-matching bug covered separately below: a
    family that already has more than one
    member (e.g. from an earlier `version` bump) where the SUPERSEDED
    member isn't the latest one already selects the wrong file -- reject
    would revert the untouched latest member and leave the real
    predecessor permanently, silently Superseded."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-01"])
    version.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    v02_path = tmp_path / "doc" / "adr" / "ADR001V02-first-decision.md"
    approve.run(["--file", str(v02_path), "--refdate", "2026-01-03"])

    # Supersede the OLDER member (V01), not the latest (V02).
    result = supersede.run(["--file", str(adr_path), "--refdate", "2026-01-04"])
    successor_path = Path(result["created"])

    reject.run(["--file", str(successor_path), "--refdate", "2026-01-05"])

    v01_text = adr_path.read_text(encoding="utf-8")
    v02_text = v02_path.read_text(encoding="utf-8")
    assert "|Superseded||" in v01_text, "V01 (the real predecessor) should have been un-superseded"
    assert "|Superseded|Superseded" not in v02_text, "V02 was never superseded and must stay untouched"


def test_reject_matches_the_predecessor_by_back_reference_not_merely_by_being_superseded(tmp_path):
    """Reverts the
    predecessor by matching its own superseded_by_file back-reference,
    not merely "a Superseded sibling" -- but every existing test only
    ever has ONE Superseded member in the family at the point reject
    runs, so "the only Superseded sibling" and "the sibling whose own
    back-reference names this successor" were indistinguishable. This
    constructs a family with TWO independently-Superseded members (hand-
    written via _write_raw, bypassing supersede's own family guard by
    design -- proving the SELECTION logic itself, not reachable through
    the normal command flow) pointing to two DIFFERENT successors, and
    confirms rejecting one successor reverts the matching predecessor,
    not just whichever Superseded sibling scan_decisions happens to
    return first."""
    tmp_path, _ = _setup_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")

    v01_path = adr_dir / "ADR001V01-first-decision.md"
    _write_raw(
        v01_path,
        cfg,
        number=1,
        title="First decision",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 3),
        superseded_by_file="002",  # points at ADR002, NOT this test's successor (ADR003)
    )
    v02_path = adr_dir / "ADR001V02-first-decision.md"
    _write_raw(
        v02_path,
        cfg,
        number=1,
        title="First decision",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 2),
        status_update="Accepted",
        date_update=date(2026, 1, 2),
        status_change="Superseded",
        date_change=date(2026, 1, 4),
        superseded_by_file="003",  # the REAL predecessor of this test's successor (ADR003)
    )
    successor_path = adr_dir / "ADR003V01-successor--001.md"
    _write_raw(
        successor_path,
        cfg,
        number=3,
        title="Successor",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 4),
        superseded=1,
    )

    result = reject.run(["--file", str(successor_path), "--refdate", "2026-01-05"])

    assert result["undone_predecessor"] == str(v02_path)
    assert "|Superseded||" in v02_path.read_text(encoding="utf-8"), "V02 (the real predecessor) should be un-superseded"
    assert "|Superseded|Superseded" in v01_path.read_text(encoding="utf-8"), "V01 must stay untouched"


def test_reject_family_scan_incomplete_makes_no_write_at_all(tmp_path, monkeypatch):
    """Round 36 retraction: the predecessor-family scan now runs BEFORE
    any write, like every other family_members call in this codebase --
    unlike the old order, where it ran AFTER the primary write had already
    committed and needed a special partial-success re-raise merging in
    file/status. That merge is gone now: the original family-scan-
    incomplete error propagates completely unchanged, and nothing was
    written."""
    tmp_path, _ = _setup_repo(tmp_path)
    adr_dir = tmp_path / "doc" / "adr"
    cfg = load_repo_config(tmp_path / "adr-config.adrplus")

    predecessor_path = adr_dir / "ADR001V01-first-decision.md"
    _write_raw(
        predecessor_path,
        cfg,
        number=1,
        title="First decision",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_update="Accepted",
        date_update=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 3),
        superseded_by_file="002",
    )
    successor_path = adr_dir / "ADR002V01-successor--001.md"
    _write_raw(
        successor_path,
        cfg,
        number=2,
        title="Successor",
        version=1,
        status_create="Proposed",
        date_create=date(2026, 1, 3),
    )

    from adrpy.cli import reject as reject_module

    real_family_members = reject_module.family_members
    calls = {"count": 0}

    def flaky_family_members(folder, config, number, warnings=None, exclude_from_encoding_check=None):
        calls["count"] += 1
        if calls["count"] == 1:
            return real_family_members(
                folder, config, number, warnings=warnings, exclude_from_encoding_check=exclude_from_encoding_check
            )
        raise CommandError(
            "family-scan-incomplete",
            "Cannot safely scan: 1 subdirectory could not be scanned.",
            data={"folder": str(folder), "unreadable": [str(folder / "restricted")]},
            warnings=warnings,
        )

    monkeypatch.setattr(reject_module, "family_members", flaky_family_members)

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path), "--refdate", "2026-01-04"])

    assert excinfo.value.code == "family-scan-incomplete"
    # The original error's own data (which subdirectories couldn't be
    # scanned) survives completely unmodified -- no file/status merged in,
    # since nothing has been written by this point.
    assert excinfo.value.data == {"folder": str(adr_dir), "unreadable": [str(adr_dir / "restricted")]}
    assert "Rejected (2026-01-04)" not in successor_path.read_text(encoding="utf-8")
    assert calls["count"] == 2


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

    assert excinfo.value.code == "field-contains-forbidden-character"


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

    assert excinfo.value.code == "family-scan-incomplete"
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
    """Performance backlog item: has_superseded_sibling and
    has_pending_sibling each called family_members (and so scan_decisions)
    independently -- 2 full directory scans per undo call for information
    a single scan already has."""
    from adrpy.core import lifecycle

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    calls = []
    original = lifecycle.scan_decisions

    def counting_scan_decisions(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    monkeypatch.setattr(lifecycle, "scan_decisions", counting_scan_decisions)

    undo.run(["--file", str(adr_path)])

    assert len(calls) == 1


def test_undo_rejects_when_still_proposed(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "still-proposed"


def test_undo_rejects_when_sibling_superseded(tmp_path):
    """Undo's own
    family-member-superseded raise site had zero coverage (only its
    sibling family-member-pending check, below, was tested)."""
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
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 2),
        superseded_by_file="ADR002V01-something.md",
    )

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "family-member-superseded"


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


def test_undo_prioritizes_superseded_sibling_over_pending_sibling(tmp_path):
    """Superseded takes priority over pending, deliberately -- a superseded
    member means the WHOLE family this decision belonged to has already
    been replaced, which blocks it regardless of any other sibling's own
    state. No existing test constructed a family with BOTH conditions
    true at once; every existing test above exercised exactly one."""
    tmp_path, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
    config = load_repo_config(tmp_path / "adr-config.adrplus")

    superseded_sibling = tmp_path / "doc" / "adr" / "ADR001V02-first-decision-v2.md"
    _write_raw(
        superseded_sibling,
        config,
        number=1,
        title="First decision v2",
        version=2,
        status_create="Proposed",
        date_create=date(2026, 1, 1),
        status_change="Superseded",
        date_change=date(2026, 1, 2),
        superseded_by_file="ADR003V01-something.md",
    )
    pending_sibling = tmp_path / "doc" / "adr" / "ADR001V03-first-decision-v3.md"
    _write_raw(
        pending_sibling,
        config,
        number=1,
        title="First decision v3",
        version=3,
        status_create="Proposed",
        date_create=date(2026, 1, 3),
    )

    with pytest.raises(CommandError) as excinfo:
        undo.run(["--file", str(adr_path)])

    assert excinfo.value.code == "family-member-superseded"


def test_undo_does_not_block_on_an_unmigrated_legacy_sibling(tmp_path):
    """family_members applied neither
    is_structurally_valid nor counts_as_family_member -- it counted ANY
    filename-matching sibling as a family member, even one whose header
    doesn't parse at all (a hand-written legacy file nobody has run
    `migrate` on yet). has_pending_sibling's predicate
    (`status_update is None and not is_migrated`) then falsely fired for
    it, blocking undo/version/revise on the *current-scheme* family member
    during the entire window between "legacy file exists" and "migrate
    has run" -- a window that must work correctly."""
    data = json.loads(open(FIXTURE_PATH, encoding="utf-8").read())
    data["migrationpattern"] = "N00:04T04"
    config_file = tmp_path / "seed-config.json"
    config_file.write_text(json.dumps(data), encoding="utf-8")
    init.run(["--path", str(tmp_path), "--seed", str(config_file)])
    new.run(["--path", str(tmp_path), "--title", "First decision", "--refdate", "2026-01-01"])
    adr_path = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])

    # A hand-written, never-migrated legacy file sharing sequence number 1
    # (matched by the "N00:04T04" pattern: 4-digit number at position 0,
    # title starting at position 4) -- no AdrPlus header at all.
    legacy_sibling = tmp_path / "doc" / "adr" / "0001LegacyNotes.md"
    legacy_sibling.write_text("# Some legacy notes\n\nNever run through migrate.\n", encoding="utf-8")

    result = undo.run(["--file", str(adr_path)])

    assert result["status"] == "Proposed"


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
