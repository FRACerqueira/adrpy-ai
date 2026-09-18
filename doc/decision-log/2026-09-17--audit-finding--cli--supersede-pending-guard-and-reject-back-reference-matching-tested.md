# supersede's family-member-pending guard and reject's back-reference matching are now independently tested

**Front:** Test-Adequacy (round 8), Findings 1 and 4 | **Severity:** High | **Resolution:** Direct | **Round:** 8

Round 8 test-adequacy audit, Finding 1 (HIGH): round 7's fix added TWO co-equal guards to `supersede` in the same commit -- `has_superseded_sibling` and `has_pending_sibling`, mirroring `version`/`revise` -- but only the first ever got a test. Deleting the `has_pending_sibling` block entirely left the full 596-test suite green, meaning a future refactor or merge conflict could silently drop this guard with nothing to catch it.

Finding 4 (Low-Medium): reject's predecessor-matching fix (match by the actual `superseded_by_file` back-reference, not merely "a Superseded sibling") was never exercised with more than one Superseded family member -- every existing fixture has exactly one, so "the only Superseded sibling" and "the sibling whose own back-reference names this successor" were indistinguishable in every test. Reachability is currently narrow (round 7's own `family-member-superseded` guard fences off the precondition through the normal command flow), but the selection logic itself was unproven.

**Fix**: two new tests, both verified against the exact mutation that would silently reintroduce each bug (confirmed red, then restored) -- `test_supersede_refuses_when_a_sibling_in_the_family_is_still_pending` (matches the audit's own suggested 2-line repro), and `test_reject_matches_the_predecessor_by_back_reference_not_merely_by_being_superseded` (constructs a family with two independently-Superseded members via `_write_raw`, bypassing supersede's own guard by design to prove the selection logic on its own terms).
