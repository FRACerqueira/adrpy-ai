# config/init now create folderadr's new folder BEFORE the config write commits

**Front:** Resilience (round 7), Finding 3 | **Severity:** High | **Resolution:** Retraction

Round 7 resilience audit, Finding 3: `config --folderadr` and `init --seed` (on an already-existing repo) both committed the `folderadr` change to disk BEFORE creating the new folder. If that folder creation then failed, the command reported a bare `io-error` with no `data` naming that the config was already mutated, and every subsequent mutating command failed with a generic `io-error` (the lock's own `_try_create` requires the parent directory to exist) until someone noticed and manually retried the same `config`/`init --seed` call.

This retracts the reasoning recorded in `2026-09-16--audit-finding--config--folderadr-change-blocked-by-existing-decisions.md`, which described `config.py`'s mkdir-after-write ordering as deliberately "matching init's own mkdir-after-write precedent." That precedent itself was the defect, not a safe pattern to match -- reproduced live (a monkeypatched `mkdir` failure) confirms `folderadr` was left committed to a directory that never existed.

**Fix**: both commands now create the new folder first -- a failure there aborts cleanly with nothing yet written. `mkdir` is otherwise harmless if the write still somehow fails afterward (an unused empty folder, not a real cost). `init`'s own `created` list still reports config-then-folder, unchanged for callers -- only the underlying filesystem operation order changed, not what's reported.
