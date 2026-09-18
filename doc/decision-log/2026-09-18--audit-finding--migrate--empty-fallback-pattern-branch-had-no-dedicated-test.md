# migrate's "fallback exists but its own pattern is empty" branch had no dedicated test

**Front:** Test-Adequacy | **Severity:** Low | **Resolution:** Direct | **Round:** 11

ADR002V01 part 3 names a specific precondition for `migration-pattern-not-configured`: "if `migrationpattern` is empty in *both* places" -- distinct from the install-level config not existing at all. Only the "doesn't exist" case (`conftest.py`'s own default) had test coverage; the "exists, parses successfully, but its own `migrationpattern` field is `\"\"`" case, which the code handles as its own distinct branch, was never constructed by any test. Both converge on the same outcome today (not a live bug), but an ADR-stated contract had no test exercising its own stated precondition.

**Fix:** new test constructing a real install-level config whose own `migrationpattern` is empty (not absent). adrpy-ai `278f5b4`.
