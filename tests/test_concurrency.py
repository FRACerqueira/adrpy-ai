"""Regression for the Milestone 8 concurrency audit's critical finding:
core/lock.py existed, was tested in isolation, and was never actually used
by any of the commands that decide "what's the next number" -- new,
version, revise, supersede all scan the directory and pick a number with
no critical section around it. Reproduced live by the audit 10/10 times
with two concurrent `new` calls landing on the identical sequence number
(different titles, so different filenames -- the actual defect is the
DUPLICATE NUMBER, not a filename collision).

new and supersede both derive their number from a repo-wide next_number()
scan, which is where the collision is directly observable and reproducible
here. version/revise are wrapped in the same lock for the same reason (the
audit named all four sharing this critical-section gap), but each derives
its number from its own target file rather than a repo-wide scan, so
there's no equally clean two-thread collision to construct for them --
core/test_lock.py's own stress test already covers the lock mechanism
itself under heavier concurrency (6 threads).

A plain threading.Barrier synchronizes only the START of each call; with
both scan-then-write sequences fast and in-memory-cached, the two threads
often don't actually overlap on their own. A short, deterministic delay
injected right after next_number() (before either thread writes) widens
the window so the race reproduces reliably instead of being flaky in
either direction."""

import re
import threading
import time

import pytest

from adrpy.cli import approve, init, new, reject, supersede
from adrpy.core import lifecycle
from adrpy.core.errors import CommandError


def _run_concurrently(callables):
    barrier = threading.Barrier(len(callables))
    results = [None] * len(callables)
    errors = [None] * len(callables)

    def wrapper(index, fn):
        barrier.wait()
        try:
            results[index] = fn()
        except Exception as error:  # noqa: BLE001 -- captured for the assertion, not swallowed
            errors[index] = error

    threads = [threading.Thread(target=wrapper, args=(i, fn)) for i, fn in enumerate(callables)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)

    assert all(not thread.is_alive() for thread in threads), "a concurrent command hung"
    return results, errors


def _sequence_number(created_path):
    match = re.search(r"ADR(\d+)", created_path)
    return int(match.group(1))


def _widen_the_race_window(monkeypatch, module):
    """Delays the return of next_number() just long enough that a second
    thread, started concurrently, reaches its own next_number() call
    before the first thread has written anything -- deterministically
    reproducing the race instead of relying on incidental OS scheduling."""
    original = lifecycle.next_number

    def delayed(decisions):
        result = original(decisions)
        time.sleep(0.1)
        return result

    monkeypatch.setattr(module, "next_number", delayed)


def test_concurrent_new_calls_never_collide_on_the_same_sequence_number(tmp_path, monkeypatch):
    init.run(["--path", str(tmp_path)])
    _widen_the_race_window(monkeypatch, new)

    results, errors = _run_concurrently(
        [
            lambda: new.run(["--path", str(tmp_path), "--title", "Decision A"]),
            lambda: new.run(["--path", str(tmp_path), "--title", "Decision B"]),
        ]
    )

    assert errors == [None, None]
    numbers = [_sequence_number(result["created"]) for result in results]
    assert numbers[0] != numbers[1], f"both calls got sequence number {numbers[0]}"
    assert sorted(numbers) == [1, 2]


def test_concurrent_supersede_calls_never_collide_on_the_same_successor_number(tmp_path, monkeypatch):
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "First decision"])
    new.run(["--path", str(tmp_path), "--title", "Second decision"])
    first = tmp_path / "doc" / "adr" / "ADR001V01-first-decision.md"
    second = tmp_path / "doc" / "adr" / "ADR002V01-second-decision.md"
    approve.run(["--file", str(first)])
    approve.run(["--file", str(second)])
    _widen_the_race_window(monkeypatch, supersede)

    results, errors = _run_concurrently(
        [
            lambda: supersede.run(["--file", str(first)]),
            lambda: supersede.run(["--file", str(second)]),
        ]
    )

    assert errors == [None, None]
    numbers = [_sequence_number(result["created"]) for result in results]
    assert numbers[0] != numbers[1], f"both successors got sequence number {numbers[0]}"
    assert sorted(numbers) == [3, 4]


def test_concurrent_approve_and_reject_on_the_same_file_do_not_both_succeed(tmp_path, monkeypatch):
    """Round 4 stability audit, Finding 1, reproduced: approve/reject held
    no repository lock at all, so two concurrent calls on the same
    Proposed file each independently read-decided-wrote and both reported
    success with mutually exclusive final statuses -- a lost update, with
    neither caller told a conflict happened. ADR001 (doc/adr/ADR001V01...)
    closes this by giving both commands the same lock new/supersede/
    version/revise already use, with the eligibility read happening
    fresh, inside it -- so the second command to actually acquire the
    lock sees the first one's already-committed status and fails cleanly
    instead of silently clobbering it."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Decision"])
    target = tmp_path / "doc" / "adr" / "ADR001V01-decision.md"

    original = lifecycle.rewrite_status_field

    def delayed(*args, **kwargs):
        time.sleep(0.1)
        return original(*args, **kwargs)

    monkeypatch.setattr(approve, "rewrite_status_field", delayed)
    monkeypatch.setattr(reject, "rewrite_status_field", delayed)

    results, errors = _run_concurrently(
        [
            lambda: approve.run(["--file", str(target)]),
            lambda: reject.run(["--file", str(target)]),
        ]
    )

    successes = [r for r in results if r is not None]
    failures = [e for e in errors if e is not None]
    assert len(successes) == 1, f"expected exactly one of approve/reject to succeed, got: {results}"
    assert len(failures) == 1, f"expected exactly one clean failure, got: {errors}"
    assert isinstance(failures[0], CommandError)


def test_concurrent_supersede_calls_on_the_same_predecessor_do_not_both_succeed(tmp_path, monkeypatch):
    """Round 4 stability audit, Finding 2, reproduced: supersede captured
    the predecessor's header/lines via load_target BEFORE acquiring the
    lock, so two concurrent supersede calls on the SAME predecessor each
    wrote it from their own stale, pre-lock snapshot -- both successors
    got created (the lock genuinely prevents a NUMBER collision, per the
    test above), but the predecessor's own header ends up referencing
    only whichever wrote last, permanently orphaning the other successor
    with no back-reference from the predecessor at all. ADR001 closes
    this by reading the predecessor fresh, inside the lock, so the second
    call sees it already Superseded and fails cleanly."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Predecessor"])
    predecessor = tmp_path / "doc" / "adr" / "ADR001V01-predecessor.md"
    approve.run(["--file", str(predecessor)])

    original = supersede.ineligibility_reason_for_supersede

    def delayed(*args, **kwargs):
        result = original(*args, **kwargs)
        time.sleep(0.1)
        return result

    monkeypatch.setattr(supersede, "ineligibility_reason_for_supersede", delayed)

    results, errors = _run_concurrently(
        [
            lambda: supersede.run(["--file", str(predecessor)]),
            lambda: supersede.run(["--file", str(predecessor)]),
        ]
    )

    successes = [r for r in results if r is not None]
    failures = [e for e in errors if e is not None]
    assert len(successes) == 1, (
        f"expected exactly one supersede on the same predecessor to succeed, got: {results}"
    )
    assert len(failures) == 1, f"expected exactly one clean failure, got: {errors}"
    assert isinstance(failures[0], CommandError)


def test_pre_commit_lock_recheck_aborts_the_write_if_the_lock_was_stolen(tmp_path, monkeypatch):
    """Round 4 ADR001, part 3 (pre-commit ownership recheck): no bounded-
    lease lock without heartbeat can prevent a legitimately slow holder's
    lock from being reclaimed by another process mid-critical-section --
    but the write that follows must never commit blindly once that's
    happened. Simulates a steal happening immediately before the write
    and confirms the command aborts with a distinct `lock-lost` code
    instead of silently overwriting the file the new holder may already
    be using, and that the file itself was never touched."""
    init.run(["--path", str(tmp_path)])
    new.run(["--path", str(tmp_path), "--title", "Decision"])
    target = tmp_path / "doc" / "adr" / "ADR001V01-decision.md"
    original_content = target.read_text(encoding="utf-8")

    # Steals the lock during the eligibility check -- the step immediately
    # before the pre-commit recheck in approve.run() -- so the recheck
    # itself (not the write it guards) is what's under test here.
    original_check = approve.ineligibility_reason_for_approve_or_reject

    def steal_lock_then_check(header):
        lock_path = tmp_path / "doc" / "adr" / ".adrpy.lock"
        lock_path.write_text(f"someone-else-entirely\n{time.time()}")
        return original_check(header)

    monkeypatch.setattr(approve, "ineligibility_reason_for_approve_or_reject", steal_lock_then_check)

    with pytest.raises(CommandError) as excinfo:
        approve.run(["--file", str(target)])

    assert excinfo.value.code == "lock-lost"
    assert target.read_text(encoding="utf-8") == original_content
