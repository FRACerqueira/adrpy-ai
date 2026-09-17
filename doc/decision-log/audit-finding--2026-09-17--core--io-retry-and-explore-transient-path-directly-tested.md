# read_with_permission_retry and explore's transient-retry path are now directly tested

**Front:** Test-Adequacy (round 8), Findings 3 and 5 | **Severity:** Low | **Resolution:** Direct

Round 8 test-adequacy audit, Finding 5: the shared `read_with_permission_retry` helper (`core/io_retry.py`) had no direct unit test of its own contract -- every exercise of it was indirect, through one specific caller's own test (`_read_lock`'s, or `lifecycle.py`'s read functions). Nothing proved the helper's exact retry count, delay, that only `PermissionError` is retried (not `FileNotFoundError` or anything else), or the `attempts=1` boundary.

Finding 3 (Low-Medium): round 7's `explore` fix does two things -- retries a TRANSIENT `PermissionError`, and treats a PERSISTENT one as a skippable, warned file. Round 7's own test only proved the second half; removing the retry wrapper entirely (leaving the persistent-skip behavior unchanged) still left the full suite green.

**Fix**: `tests/test_io_retry.py` (new file) directly tests the helper's contract in isolation -- this also closes the root mechanism behind Finding 3, per the audit's own suggestion. A new companion test, `test_explore_retries_a_transient_permission_error_instead_of_skipping_the_file`, proves a file that fails twice then succeeds appears normally with no warning, not skipped -- verified against the exact mutation that would silently drop the retry wrapper.
