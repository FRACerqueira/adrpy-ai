# _try_create's os.open and _reclaim_if_abandoned's stat() now retry a transient PermissionError

**Front:** Stability (round 6), Finding A-3, corroborated by a second independent instance | **Severity:** Medium (upgraded from the original pass's Medium-low on corroboration) | **Round:** 6

Round 6 stability re-run, Finding A-3: `_try_create` (the lock file's own creation, `os.open(..., O_CREAT|O_EXCL|O_WRONLY)`) was the one lock-file operation in `core/lock.py` with no tolerance at all for the same Windows "pending delete"/sharing-violation contention window `_read_lock` and `_unlink_with_retry` already retry.

**Corroborated independently** (own instance, no shared context, asked specifically to verify or refute this finding): confirmed the uniqueness claim by reading the file directly; reproduced the mechanism two ways (mocked `os.open`, and 8 real separate OS processes hammering the real, unmodified `acquire_repo_lock` on real NTFS -- ~14% of create attempts collided over an 8s stress run, every one attributed to this exact call). Refuted the original finding's own "not reproducible from pure CPython" caveat for genuine cross-process racing (only the specific held-open-handle technique it tried doesn't work on Windows) and recommended upgrading severity from Medium-low to Medium -- accepted: this is the third and last unfixed sibling of the identical pattern in this one file (round 4 fixed `_read_lock`, round 5 fixed the release-path read).

The corroborating pass also found a related, not-yet-triggered gap in the same sweep: `_reclaim_if_abandoned`'s two `path.stat()` calls (the malformed-lock-file fallback) only tolerated `FileNotFoundError`, not the same transient `PermissionError` -- same contention class, closed together.

**Fix**: both now retry a transient `PermissionError` via the same shared `core/io_retry.read_with_permission_retry` helper already used elsewhere in this file, with `_try_create`'s own persistent failure (past the retry budget) getting the identical, already-safe treatment as `FileExistsError` -- return `False`, let the wait loop's own timeout handle it, rather than escaping raw as a generic `io-error`.
