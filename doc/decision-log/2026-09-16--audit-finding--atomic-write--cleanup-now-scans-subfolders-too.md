# cleanup_orphaned_temp_files now scans subfolders too

**Front:** Stability (round 7), Low finding | **Severity:** Low | **Resolution:** Direct | **Round:** 7

Round 7 stability audit: `cleanup_orphaned_temp_files` used a non-recursive `directory.glob("*.tmp")`, while every other scan in this codebase (`scan_decisions`, `migrate`'s own scan, `explore`, `init`'s `_max_existing_numbers`) already uses `rglob` to also cover subfolders under `folderadr`. An orphan left inside a subfolder was never found or reported -- a housekeeping leak, not a correctness issue (temp files never collide by name and are never read by anything).

**Fix**: switched to `rglob("*.tmp")`, matching every sibling scan already in this codebase.
