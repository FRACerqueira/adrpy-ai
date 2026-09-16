# migrate's tool-created-ADR gate and the .md auto-suffix are now documented

**Front:** Usability (round 5 re-run), Findings 5 and 7 | **Severity:** Low

Round 5 backlog, Fase 2 (isolated per-file documentation, no shared code): Finding 5 -- `migrate`'s already-tool-created-adrs-exist code was only mentioned in passing (as part of explaining the encoding-unreliable refusal); its own trigger condition (refuses the ENTIRE run, no file touched, if even one scanned file already has a valid, non-migrated header) was never actually stated. Finding 7 (pre-existing, minor) -- the 6 per-file commands (approve/reject/undo/supersede/version/revise) never documented that `resolve_repo_and_target` silently appends `.md` to a `--file` with no extension.

**Fix**: both documented; new cross-command test confirms all 6 commands document the auto-suffix.
