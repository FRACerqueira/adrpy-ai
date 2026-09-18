# migrate now documents migration-scan-failed alongside its sibling migration-scan-unreliable-encoding

**Front:** Usability (round 7), Finding 5 | **Severity:** Low | **Resolution:** Direct | **Round:** 7

Round 7 usability audit, Finding 5: `migrate`'s `describe()` gave a full paragraph to `migration-scan-unreliable-encoding` but never mentioned its structurally identical sibling `migration-scan-failed` -- same scan loop, same phase, same all-or-nothing semantics (`data.unreadable_file` names the one file), just a real `OSError` (permission denied or similar) instead of a lossy decode.

**Fix**: `describe()` now documents `migration-scan-failed` alongside its sibling.
