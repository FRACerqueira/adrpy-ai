# init --seed's description didn't mention it also bypasses the install-level config

**Front:** Usability | **Severity:** Low | **Resolution:** Direct | **Round:** 11

`init.py`'s `--seed` argument description read "instead of the built-in default," accurate before ADR002V01 but stale since: `--seed` also bypasses the install-level config (never even read when `--seed` is given, per `install_config_text = None if seed_arg is not None else read_install_config_text()`), not just the bundled default.

**Fix:** description extended to name both alternatives it overrides. adrpy-ai `4d82efa`.
