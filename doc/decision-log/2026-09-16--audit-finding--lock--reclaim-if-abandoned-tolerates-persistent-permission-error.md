# _reclaim_if_abandoned's own _read_lock calls now tolerate a persistent PermissionError

**Front:** Resilience (round 7), Finding 2 | **Severity:** Medium | **Resolution:** Direct | **Round:** 7

Round 7 resilience audit, Finding 2: `_reclaim_if_abandoned`'s two `_read_lock(path)` calls (parsed-lock branch) had no tolerance at all for a PERSISTENT `PermissionError` -- unlike its sibling `path.stat()` calls in the malformed-lock-file fallback, hardened in round 6. A persistent failure here escaped raw out of `acquire_repo_lock`'s own wait loop, losing the purpose-built `repository-locked`/`lock-lost` reporting this mechanism exists to guarantee. Reproducible with an external actor (antivirus, editor, backup tool) holding the lock file open; a 30-/60-way concurrent `adrpy`-vs-`adrpy` stress test alone never triggered it (adrpy's own lock handles close too quickly to reliably exceed the retry budget), so this needs an external holder or pathological filesystem latency to occur in practice -- rated Medium rather than High for that reason, though the code-path gap itself is real and corroborated, not hypothetical.

**Fix**: both `_read_lock` calls now caught for `PermissionError`, returning `False` (abstain, don't reclaim) on a persistent failure -- ownership can't be confirmed either way, so treat it exactly as protectively as every other persistent-failure case in this module.
