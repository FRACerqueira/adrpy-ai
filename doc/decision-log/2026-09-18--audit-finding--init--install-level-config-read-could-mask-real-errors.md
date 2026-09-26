# install-level config read ran before target/existence checks, could mask real errors

**Front:** Stability | **Severity:** Low | **Resolution:** Direct | **Round:** 11

`init.py`'s `read_install_config_text()` call ran unconditionally before `target.is_dir()` and the `config-already-exists` check -- real file I/O plus schema validation against a file the caller never named. A corrupted per-user install-level config (external tampering only; `installconfig` itself always validates before writing) would mask `target-directory-not-found`/`config-already-exists` with an unrelated schema error.

**Fix:** moved the read (and the `--language` exclusion check depending on it) to after both existence checks, verified to still fire correctly on every reachable case. adrpy-ai `4d82efa`. Two new red-then-green tests.
