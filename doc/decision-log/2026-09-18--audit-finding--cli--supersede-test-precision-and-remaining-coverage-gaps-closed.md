# supersede's ambiguous test tightened; remaining CLI/data-completeness coverage gaps closed

**Front:** Test-Adequacy (round 9), Findings 2, 3, 4 and 5 | **Severity:** Low-Medium | **Resolution:** Direct | **Round:** 9

Round 9 test-adequacy audit, Finding 2 (Low-Medium): `supersede`'s own fail-closed test accepted either of two error codes (`family-scan-incomplete` OR `supersede-successor-scan-incomplete`), which meant it couldn't tell "the guard the docstring says fires" from "a different guard happened to also fire" -- it did not notice when Finding 1's mutation disabled `family_members`' own strict scan, since `supersede`'s second, independent successor-number scan coincidentally covered for it.

Finding 3 (Low): `folderadr-change-scan-incomplete` had no CLI-level test through either real caller (`config`, `init --seed`), only a core/lifecycle unit test. Finding 4 (Low): `family_members`' own fail-closed test never checked `data["unreadable"]`, unlike its sibling tests. Finding 5 (Low, out of round 8's stated scope): `find_unreadable_subdirectories` was never exercised with more than one blocked subdirectory at once -- a message/accumulation completeness gap, not a correctness one.

**Fix**: tightened the `supersede` test's assertion to the single deterministic code (the OTHER code's own wiring is already proven independently by its own companion test); added CLI-level tests for `config`/`init --seed`; strengthened `family_members`' own test to check `data["unreadable"]`; added a two-simultaneously-blocked-subdirectories test for `find_unreadable_subdirectories`.
