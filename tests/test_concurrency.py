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

from adrpy.cli import approve, init, new, supersede
from adrpy.core import lifecycle


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
