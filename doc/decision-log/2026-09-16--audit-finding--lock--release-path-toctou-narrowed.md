# The lock release path's own read-then-unlink TOCTOU was narrowed

**Front:** Stability (round 5 re-run), Finding 6 | **Severity:** Low | **Round:** 5

Round 5 stability re-run, Finding 6: `acquire_repo_lock`'s `finally` block read the lock once to confirm ownership, then unlinked -- if a reclaim landed in that window (only possible past the 30s abandon window), this process could delete the NEW owner's lock file. `_reclaim_if_abandoned` already documented and guarded against the equivalent window for its own removal decision (`if _read_lock(path) != existing: return False`); the release path's own equivalent check was missing.

Fixed: re-reads immediately before the unlink, aborting if anything changed since the first read -- same guard shape as `_reclaim_if_abandoned`'s own inner check.

**Why not fully closed:** no atomic compare-and-delete exists at the filesystem level -- a second read narrows the window as far as it can, it cannot eliminate it. This is the same accepted residual `_reclaim_if_abandoned`'s own docstring already documents for its identical mechanism. No named condition to revisit this further exists (closing it completely would need a different locking primitive entirely, not a scheduled follow-up), so this stays the accepted shape going forward.
