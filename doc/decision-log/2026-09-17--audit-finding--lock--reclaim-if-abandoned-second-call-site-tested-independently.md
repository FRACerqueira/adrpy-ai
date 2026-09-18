# _reclaim_if_abandoned's second _read_lock call site is now tested independently of the first

**Front:** Test-Adequacy (round 8), Finding 2 | **Severity:** Medium | **Resolution:** Direct | **Round:** 8

Round 8 test-adequacy audit, Finding 2: round 7's own test (`test_reclaim_if_abandoned_returns_false_when_read_lock_itself_persistently_fails`) blanket-replaces `_read_lock`, so the FIRST call (the initial read) fails and the function returns `False` immediately -- the SECOND call site's own `except PermissionError` (the recheck-before-unlink) was never actually reached by that test or any other, despite the round-7 decision-log entry's own docstring claiming to protect "both" calls.

**Fix**: `test_reclaim_if_abandoned_returns_false_when_only_the_second_read_lock_call_persistently_fails` lets the first `_read_lock` call succeed normally (a genuinely abandoned lock, past `abandon_after`) and fails only the second -- verified against the exact mutation that would silently drop that specific `except` clause (confirmed red, then restored).
