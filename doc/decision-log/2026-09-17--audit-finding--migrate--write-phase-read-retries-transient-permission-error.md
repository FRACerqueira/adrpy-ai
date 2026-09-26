# migrate's write-phase read now retries a transient PermissionError, matching its own scan-phase read of the same file

**Front:** Resilience (round 8), Finding 2 | **Severity:** Medium | **Resolution:** Direct | **Round:** 8

Round 8 resilience audit, Finding 2: the write-phase read of a candidate's own bytes (`candidate_path.read_bytes()`) had no retry tolerance, unlike this command's own SCAN-phase read of the exact same file a few dozen lines earlier (`read_header_lines_with_report`, already retried). A transient blip here permanently misclassified the candidate as `"failed"` (caught by the per-candidate `except (OSError, UnicodeError)`) in what this command's own docstring calls "a one-time, largely irreversible operation" -- worse than a generic failure, since it committed a wrong, permanent verdict about that one file.

**Fix**: the write-phase read now goes through the shared `read_with_permission_retry` helper, matching its own scan-phase sibling.
