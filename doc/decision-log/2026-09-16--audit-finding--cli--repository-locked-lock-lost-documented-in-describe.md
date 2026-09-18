# repository-locked and lock-lost are now documented on every locked command's describe()

**Front:** Usability (round 5 re-run), Finding 1 | **Severity:** High | **Round:** 5

Round 5 re-run, Finding 1: `repository-locked` and `lock-lost` are the ADR001-designed failure boundary for every one of the 9 write commands plus `init`'s own `--seed`-on-existing-repo path, but were undocumented anywhere on the caller-facing `describe()` surface -- an agent had no way to learn these codes exist short of reading `core/lock.py`'s own source.

**Fix**: documented uniformly everywhere -- `lock-lost` always means "no write was made" now, with `supersede`/`reject` noting their second write surfaces its own existing code instead (matching this same round's F3 fix). New cross-command test confirms every locked command's `describe()` mentions `repository-locked`.
