# migrate reports what it migrated on any unexpected error and never lists a failed file twice

**Front:** Round 45: resilience of the Round 44 additions | **Severity:** Low | **Resolution:** Direct | **Round:** 45

migrate accounted only for KeyboardInterrupt and CommandError: a RuntimeError after migrating a file returned internal-error with no results. It now accounts for any BaseException, as commit_in_order does (detail Interrupted (<error>)). A stale in_flight left by a failed file could list that file twice in data.results; it is reset after a per-file failure (572c5c7).
