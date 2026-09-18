# acquire_repo_lock's release-path read failure could leak the lock or mask a real error

**Front:** Stability (round 5 re-run, Opus), Finding 2 | **Severity:** Medium

Round 5 stability re-run (Opus), Finding 2: `acquire_repo_lock`'s own `finally` block called `_read_lock` first, to confirm ownership before unlinking -- but `_read_lock` still raises past its own retry budget on a persistent `PermissionError`, and any other `OSError` immediately. Either escaping the `finally` block (a) skipped `_unlink_with_retry` entirely, leaking the lock file for the full 30s `ABANDON_AFTER_SECONDS` window (no single command invocation waits that long), and (b) since a `finally`-raised exception supersedes whatever was propagating from the `try: yield lock` block, could replace a real `CommandError` (e.g. `already-accepted`) with a generic `io-error`, discarding the structured code. Reproduced deterministically (a mocked `_read_lock` raising `OSError`/a persistent `PermissionError`).

Residual of round 4's own fix for `_unlink_with_retry` (its docstring already describes this exact symptom) -- missing from its neighbor, called first in the same block. Fixed: the release-path read is now best-effort, matching `_unlink_with_retry`'s own contract -- if ownership can't be confirmed, leave the file for a later reclaim instead of raising or guessing. `core/lock.py`, tests in `test_lock.py`.
