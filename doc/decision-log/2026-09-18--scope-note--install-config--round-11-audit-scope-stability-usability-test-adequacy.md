# Round 11 audit scope: Stability, Usability, and Test-Adequacy on the install-level config module

Reactive-trigger round (per the model adopted after round 10 -- a front runs again only when a concrete change lands in its own territory, not a periodic cadence), triggered by ADR002V01's own implementation landing in this same session: `core/install_config.py` (new), `cli/installconfig.py` (new), `cli/init.py` (modified consumption), `cli/migrate.py` (modified -- the `migrationpattern`-empty check moved inside the repository lock, with a new persist-back write added there).

**Three angles confirmed:**

1. **Stability/Concurrency** -- `migrate.py` gained a genuinely new write path (persist-back) inside its already-locked critical section, and `installconfig.py` is a new command deliberately built with no repository lock (ADR002V01's own decision) -- warrants independent adversarial scrutiny of that "no lock needed" reasoning, not just the implementer's own confirmation. Reads: `core/install_config.py`, `cli/installconfig.py`, `cli/migrate.py`, `cli/init.py`, ADR001V01, ADR002V01.
2. **Usability** -- three `describe()` surfaces changed or were added this session (`init`, `migrate`, `installconfig`), with new precedence rules (`--language` vs. an existing install-level config) and new response shapes (`configured`/`config` vs. `updated_fields`). Reads: the three commands' `describe()` text against their real `run()` behavior.
3. **Test-Adequacy** -- every new test in this area was written by the same session that wrote the implementation; this project's own history (round 9) already found self-authored coverage claims that weren't actually tested end-to-end. Reads: `tests/conftest.py`, `tests/test_install_config.py`, `tests/test_installconfig.py`, and the new/modified tests in `tests/test_init.py`/`tests/test_migrate.py`.

Calibration against rounds 1-10 (context, not a deciding factor -- this is new territory, not a re-run): Stability 8/15/19/9/8/1 (full arc, last round already confirmation-shaped), Usability 12/11/8 (declining), Test-Adequacy 3/12/11 (least mature, 2 data points).
