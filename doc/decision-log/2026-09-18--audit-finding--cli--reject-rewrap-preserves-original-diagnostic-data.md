# reject's family-scan-incomplete re-raise now preserves the original error's own diagnostic data

**Front:** Stability (round 10, confirmation pass triggered by round 9's reject.py change) | **Severity:** Low | **Resolution:** Direct | **Round:** 10

Round 10 stability audit, Finding 1: round 9's fix (`2026-09-18--audit-finding--cli--reject-partial-success-data-and-init-scan-incomplete-doc-fixed.md`) re-raised `family_members`' `family-scan-incomplete` with `data={"file": str(path), "status": "Rejected"}`, replacing the original error's own `data` wholesale instead of merging. `scan_decisions`' own raise (`core/lifecycle.py`) carries `data={"folder": ..., "unreadable": [...]}` -- the only place naming which subdirectories couldn't be scanned, since this raise happens before `scan_decisions`' own warnings block would otherwise also report it. The wholesale replacement discarded that information irrecoverably; `__main__.py` puts `data` directly into the CLI's JSON output, so this was caller-visible, not just internal. No data corruption, no wrong write -- a diagnostic-payload regression on one failure path, not a concurrency defect.

Confirmation-pass context: this round was deliberately scoped to scrutinize round 9's own new `try/except CommandError` block specifically (does it change what the lock's `verify_still_held()` protects, could it mask a different error code, does it interact badly with `attach_warnings`) -- all four came back clean; this was the one real finding.

**Fix**: `data={**(error.data or {}), "file": str(path), "status": "Rejected"}` -- merges instead of replaces.

Architectural review (Round 43): the re-raise this entry fixed no longer exists: reject reads the predecessor's family from the snapshot validated before any write, and `family-scan-incomplete` gave way to the validator's `scan-incomplete`. The `verify_still_held()` check mentioned went with the lock (ADR001).
