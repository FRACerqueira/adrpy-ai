# family-scan-incomplete is now covered end-to-end for approve/reject/undo/version/revise

**Front:** Test-Adequacy (round 9), Finding 1 | **Severity:** High | **Resolution:** Direct

Round 9 test-adequacy audit, Finding 1 (HIGH): round 8's own decision log claimed these 5 commands "inherit [family_members' fail-closed fix] for free" from the shared mechanism -- but nothing end-to-end proved it for any of them. Only `supersede` had a test touching this path (itself ambiguous, see the companion entry), and only `family_members` itself had a direct core-level test. Demonstrated: wrapping each command's own `family_members` call in `try/except CommandError: members = []` (a plausible future "degrade gracefully" refactor) left the full 616-test suite green for all 5.

**Fix**: one new end-to-end test per command, each verified against the exact mutation the audit demonstrated (confirmed red, then restored).
