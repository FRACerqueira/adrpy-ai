# conftest.py's install-level-config isolation fixture didn't document its own scope

**Front:** Test-Adequacy | **Severity:** Low | **Resolution:** Direct | **Round:** 11

`conftest.py`'s autouse fixture isolates `init`/`migrate` from the real per-user install-level config path; `installconfig` is isolated separately, locally, by its own file's own fixture (`tests/test_installconfig.py`). No live bug (grep-confirmed: no other test currently calls `installconfig.run()`), but nothing said this split existed, or that a future test calling `installconfig.run()` from anywhere else would leak to the real machine's own config file unnoticed.

**Fix:** one paragraph added to the fixture's own docstring naming exactly what is and isn't covered. adrpy-ai `41264a7`.
