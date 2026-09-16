import json
import os
import time
from datetime import date, timedelta
from pathlib import Path

from adrpy.__main__ import main
from adrpy.cli import approve, init, new, reject, undo
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

    assert excinfo.value.code == "already-accepted"


def test_approve_rejects_a_corrupted_status_update_end_to_end(tmp_path):
    """Audit round 2 regression, confirmed live at the CLI level: a
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
    """Round 4 resilience audit, Finding 1, reproduced: encoding_repaired_
    warning claims "the file has been rewritten... bytes are now lost" --
    false whenever the command fails before ever reaching its own write.
    Confirmed live: approve on an already-Accepted, encoding-corrupted
    file used to report this claim anyway, even though the file was never
    touched by this call."""
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
    """Round 4 test-adequacy audit, Finding 4: retry_warning's own
    "succeeded only after N attempts" message had no end-to-end coverage
    proving it actually reaches a command's own result (only approve.py's
    encoding-repair warning, and new.py's happy path, were ever checked
    for warnings content at all). approve/reject/undo write through
    core.lifecycle.rewrite_status_field, which calls atomic_write_text
    from ITS OWN module namespace -- patching approve.py's own (absent)
    reference would silently no-op."""
    from adrpy.core import lifecycle

    _, adr_path = _setup_repo(tmp_path)
    real_atomic_write_text = lifecycle.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(lifecycle, "atomic_write_text", flaky_atomic_write_text)

    result = approve.run(["--file", str(adr_path)])

    assert any("3 attempts" in w for w in result["warnings"])


def test_approve_reports_warnings_accumulated_before_an_unrelated_failure(tmp_path):
    """Mechanism-correctness audit round 2 (findings #3/#4): a warning
    already recorded earlier in the same run (here, an orphaned temp-file
    cleanup, which runs before the lock/eligibility check either way) used
    to be silently discarded the moment the command went on to fail for an
    unrelated reason (here, the decision is already Accepted) -- nothing
    in the failure response revealed that the cleanup had already happened
    for real.

    Round 4 note (resilience audit Finding 1): this used to use an
    encoding-repair warning for the same purpose, but that warning is now
    only ever appended after the write it describes genuinely happens --
    `already-accepted` fails before any write, so it's no longer a valid
    example of "a warning that already happened before this failure"."""
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path), "--refdate", "2026-01-02"])
    orphan_path = adr_path.parent / "orphan.md.abc123.tmp"
    orphan_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 999
    os.utime(orphan_path, (old_time, old_time))

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-accepted"
    assert excinfo.value.warnings
    assert any("orphaned" in w.lower() for w in excinfo.value.warnings)


def test_approve_reports_warnings_when_a_core_helper_raises(tmp_path):
    """Class-closure check (advisor-caught gap): the fix above only threaded
    `warnings` through raise sites living directly in the 8 command files.
    The same invariant is violated just as easily by a CommandError raised
    from a shared core/ helper (here, validate_refdate_not_before, called
    from approve.py) while `warnings` already has entries in scope --
    textually unrelated to the sites already patched, but the same bug.

    Round 4 note (resilience audit Finding 1): uses an orphaned temp-file
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


def test_reject_reveals_partial_success_when_predecessor_is_missing(tmp_path):
    """Mechanism-correctness audit round 2 (findings #3/#4), the most
    serious instance: reject's primary write (marking THIS file Rejected)
    already succeeds before it discovers the predecessor it's supposed to
    un-supersede doesn't exist. The previous failure response revealed
    nothing about the mutation that had already happened for real."""
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
    assert excinfo.value.data == {"file": str(successor_path), "status": "Rejected"}
    assert "|Changed|Rejected" in successor_path.read_text(encoding="utf-8")


def test_reject_reports_two_warnings_together_in_order_before_an_unrelated_failure(tmp_path):
    """Test-adequacy audit round 3: no existing test had more than one
    warning accumulated simultaneously before a later failure -- which
    quietly weakens every `assert excinfo.value.warnings` check elsewhere
    (they'd still pass even with a duplicated warning or the wrong
    order). This combines two distinct real side effects (an orphaned
    temp-file cleanup AND an encoding repair) surviving together to a
    later, unrelated CommandError, and checks both content and order.

    Round 4 note (resilience audit Finding 1): previously used `approve`
    failing on family-member-superseded, a failure that happens BEFORE
    any write -- encoding_repaired_warning now only fires once the write
    it describes has actually happened (this test's own point predates
    that fix, and was itself asserting the bug). `reject` on a successor
    whose predecessor is missing is the natural home for this now: its
    own target write genuinely succeeds first (encoding_repaired_warning
    becomes true), and the LATER, unrelated failure is discovering the
    predecessor doesn't exist -- both warnings are real by the time they
    survive to that failure, not merely by coincidence of timing."""
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
    with open(successor_path, "ab") as handle:
        handle.write(b"Invalid byte here: \xa4 end.\n")

    orphan_path = adr_dir / "orphan.md.abc123.tmp"
    orphan_path.write_text("stale", encoding="utf-8")
    old_time = time.time() - 999
    os.utime(orphan_path, (old_time, old_time))

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(successor_path)])

    assert excinfo.value.code == "superseded-predecessor-not-found"
    assert len(excinfo.value.warnings) == 2
    assert "orphaned" in excinfo.value.warnings[0].lower()
    assert "rewritten" in excinfo.value.warnings[1].lower()


def test_reject_reveals_target_already_rejected_when_predecessor_write_fails(tmp_path, monkeypatch):
    """Mechanism-correctness audit round 3 (resilience finding #1): same
    partial-mutation class as test_reject_reveals_partial_success_when_
    predecessor_is_missing, but for a real OSError instead of a missing
    predecessor -- the target's own write to Rejected already succeeded
    before the predecessor's "undo Superseded" write fails."""
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

    assert excinfo.value.code == "reject-predecessor-write-failed"
    assert excinfo.value.data["file"] == str(successor_path)
    assert excinfo.value.data["status"] == "Rejected"
    assert excinfo.value.data["predecessor_file"] == str(adr_path)
    assert "|Changed|Rejected" in successor_path.read_text(encoding="utf-8")


def test_approve_rejects_refdate_before_create(tmp_path):
    _, adr_path = _setup_repo(tmp_path)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(adr_path), "--refdate", "2025-12-31"])

    assert excinfo.value.code == "refdate-before-history"
    # Test-adequacy audit round 3: the real "nothing accumulated" value a
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

    result = approve.run(["--file", str(adr_path)])

    body_bytes = adr_path.read_bytes()
    assert b"\xa4\xe9\xe8" not in body_bytes
    assert "Invalid UTF-8 marker: ��� end.".encode("utf-8") in body_bytes
    # Observability audit, end-to-end: load_target's own encoding_repaired
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
    assert "|Changed|Rejected (2026-01-02)|" in text


def test_reject_rejects_already_resolved(tmp_path):
    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])

    with pytest.raises(CommandError) as excinfo:
        reject.run(["--file", str(adr_path)])

    assert excinfo.value.code == "already-accepted"


def test_reject_rejects_when_sibling_superseded(tmp_path):
    """Round 4 test-adequacy audit, Finding 2: family-member-superseded
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
    """Round 4 resilience audit, Finding 1, reproduced -- same class as
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
    """Round 4 test-adequacy audit, Finding 4 -- same class as approve's
    own test."""
    from adrpy.core import lifecycle

    _, adr_path = _setup_repo(tmp_path)
    real_atomic_write_text = lifecycle.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(lifecycle, "atomic_write_text", flaky_atomic_write_text)

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
        superseded_by_file="ADR002V01-successor--001.md",
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


def test_undo_does_not_claim_a_rewrite_when_it_fails_before_writing(tmp_path):
    """Round 4 resilience audit, Finding 1, reproduced -- same class as
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
    """Round 4 test-adequacy audit, Finding 4 -- same class as approve's
    own test."""
    from adrpy.core import lifecycle

    _, adr_path = _setup_repo(tmp_path)
    approve.run(["--file", str(adr_path)])
    real_atomic_write_text = lifecycle.atomic_write_text

    def flaky_atomic_write_text(*args, **kwargs):
        real_atomic_write_text(*args, **kwargs)
        return 3

    monkeypatch.setattr(lifecycle, "atomic_write_text", flaky_atomic_write_text)

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
    """Round 4 test-adequacy audit, Finding 2: undo's own
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


def test_undo_does_not_block_on_an_unmigrated_legacy_sibling(tmp_path):
    """Legacy-scheme census audit: family_members applied neither
    is_structurally_valid nor counts_as_family_member -- it counted ANY
    filename-matching sibling as a family member, even one whose header
    doesn't parse at all (a hand-written legacy file nobody has run
    `migrate` on yet). has_pending_sibling's predicate
    (`status_update is None and not is_migrated`) then falsely fired for
    it, blocking undo/version/revise on the *current-scheme* family member
    during the entire window between "legacy file exists" and "migrate
    has run" -- a window the harness explicitly says must work."""
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
    """Fidelity audit F10: real adrplus's -f/-r; end-to-end through
    main(), not just parse_flags in isolation."""
    from adrpy.__main__ import main
    from adrpy.core.output import EXIT_SUCCESS

    _, adr_path = _setup_repo(tmp_path)

    assert main(["approve", "-f", str(adr_path), "-r", "2026-01-02"]) == EXIT_SUCCESS
    assert "|Changed|Accepted (2026-01-02)|" in adr_path.read_text(encoding="utf-8")
