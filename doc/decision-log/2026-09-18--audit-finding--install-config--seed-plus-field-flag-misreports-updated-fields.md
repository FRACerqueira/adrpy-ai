# installconfig --seed + a field flag reports the field as updated even though it never applied

**Front:** Usability | **Severity:** Medium | **Resolution:** Direct | **Round:** 11

`installconfig --seed fixture.json --prefix ZZZ` writes the fixture's own `prefix`, not `ZZZ` -- confirmed intentional (`--seed` returns before any other flag is examined), matching `tests/test_installconfig.py::test_seed_does_not_merge_with_field_flags`. But nothing in `describe()` said a co-passed field flag is dropped rather than applied, and `updated_fields` still lists it as if it had been.

**Fix (this entry):** `--seed`'s own description now states the field flag is silently ignored, not applied and not an error -- while still appearing in `updated_fields`, since `--seed` makes every field this call's own regardless. adrpy-ai `1b53975`.

**Open, not decided here:** whether the *behavior* itself should instead raise `UsageError`, matching `init`'s own precedent of erroring for its incompatible flag combination (`--seed`+`--language`), rather than silently dropping the flag -- escalated to the project owner, not resolved by this doc fix.
