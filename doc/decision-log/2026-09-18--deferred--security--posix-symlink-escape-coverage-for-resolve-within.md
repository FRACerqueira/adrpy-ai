# resolve_within's real-symlink escape test only runs on Windows

**Reopen-when:** the test-adequacy audit front runs again, or POSIX symlink-escape behavior is specifically investigated

The only test constructing a real symlink/junction on disk to prove `resolve_within` rejects a path that escapes the repository via it (`tests/test_security.py::test_resolve_within_rejects_a_path_that_escapes_via_a_real_junction`, round 4 test-adequacy audit Finding 9) is gated `skipif(sys.platform != "win32")`. No equivalent test constructs a real POSIX symlink to exercise the same invariant on that platform -- `resolve_within`'s own docstring claims it follows "real symlinks," but that claim has only ever been checked against a Windows junction, never a POSIX symlink.

This is a different class of gap from `core/install_config.py`'s own `os.name`-conditional path resolver (ADR002V01), whose POSIX branch is also untestable on this Windows host: that one is a code path picking the right OS-specific logic, provably impossible to simulate cross-platform (Python 3.12's pathlib refuses to construct a `PosixPath` on a non-POSIX host, even via monkeypatching). This one is an escape-detection invariant that should hold identically on both platforms, tested against a real filesystem construct on only one of them -- there is no structural reason a POSIX-side test couldn't exist, it simply doesn't yet.

**Why deferred, not fixed now:** found incidentally while checking `core/install_config.py`'s own OS-specific coverage at the user's prompting -- out of scope for that work, and no pre-release-audit gate is currently active (CLAUDE.md's "Pre-release audit" rule: on demand, never automatic, never a background default for routine changes).

**Reopening condition:** revisit the next time the test-adequacy front runs, or sooner if POSIX symlink-escape behavior is specifically investigated.
