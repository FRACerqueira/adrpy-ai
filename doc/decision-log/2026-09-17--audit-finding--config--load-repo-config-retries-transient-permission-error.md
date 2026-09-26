# load_repo_config now retries a transient PermissionError

**Front:** Resilience (round 8), Finding 1 | **Severity:** Medium | **Resolution:** Direct | **Round:** 8

Round 8 resilience audit, Finding 1: `read_config_text` had no `PermissionError` tolerance at all, unlike every other read in this codebase (`core/lock.py`'s `_read_lock`, `core/lifecycle.py`'s `read_lines_with_report`, `cli/explore.py`'s `_build_entry`). This read goes through the identical `atomic_write_text` -> `os.replace` mechanism those retries exist to absorb, and it runs at the start of nearly every command (`resolve_repo_and_target`'s own initial config load), most of it before any lock or `attach_warnings` safety net is entered. A stress probe (1 writer thread, 2 reader threads, real `atomic_write_text`) measured ~0.23% of reads hitting this window -- matching the ~0.2% rate already measured and retried for the sibling case in `lifecycle.py`.

**Fix**: `read_config_text` now goes through the shared `read_with_permission_retry` helper, same as every sibling read.
