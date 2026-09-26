# scan_decisions and its 3 siblings now report unreadable subdirectories instead of silently under-scanning

**Front:** Resilience (round 6), Finding B | **Severity:** Medium | **Round:** 6

Round 6 resilience re-run, Finding B, class closure: `Path.rglob` (CPython's own pathlib implementation) silently swallows any `OSError` raised while walking a subtree. A subfolder that becomes unreadable mid-scan -- an ordinary ACL choice for a team-restricted area, something `core/lock.py`'s own module docstring already anticipates -- made every `rglob("*.md")` scan in this project return fewer results, or none, with no exception and no signal at all: `scan_decisions`, `explore`, `migrate`'s own scan, and `init`'s `_max_existing_numbers` all shared this gap, not just the one call site originally reported.

**Fix**: `core.security.find_unreadable_subdirectories` uses `os.walk`'s own `onerror` hook (the one stdlib mechanism that surfaces this instead of swallowing it) purely for error detection -- every caller keeps using `folder.rglob()` unchanged for the actual scan, preserving its own junction-following behavior exactly rather than risking a traversal-mechanism swap changing what gets found.

Two different responses, matched to what's actually at stake at each call site: `scan_decisions` and its 3 siblings now report an incomplete scan as a warning -- nothing unsafe happens from an under-reported inventory there. `reject_folderadr_change_if_decisions_exist` is different: it gates a real safety decision (round 5, Finding 5), where `existing == []` is only trustworthy if the scan that produced it was complete -- fails closed instead, with a new `folderadr-change-scan-incomplete` code, rather than allowing an orphaning it couldn't actually rule out.
