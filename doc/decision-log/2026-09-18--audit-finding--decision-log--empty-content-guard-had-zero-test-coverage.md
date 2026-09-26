# _parse_entry's empty-content guard now has direct test coverage

**Front:** Test-Adequacy audit | **Severity:** High | **Resolution:** Direct | **Round:** 15

Round 15's Test-Adequacy pass confirmed round 14's `if not lines:` guard in `_parse_entry` (added to fix a raw, uncaught `IndexError` on `lines[0]` for an empty/heading-less decision-log `.md` file) is correct, but had zero test coverage anywhere in the suite -- confirmed by mutating the guard to `if False and not lines:` and observing the full suite (751 tests at the time) still pass with no failures.

If this guard regressed during a future edit to the surrounding lines, the crash it closes would ship silently again, with nothing to catch it.

Fixed by adding `test_max_existing_round_fails_closed_on_a_completely_empty_file` (tests/test_decision_log.py), verified red (the exact predicted IndexError) against the mutation above, then green after reverting.
