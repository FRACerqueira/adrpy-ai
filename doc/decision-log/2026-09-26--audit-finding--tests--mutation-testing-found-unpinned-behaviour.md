# Mutation testing found behaviour of fs, naming and consistency that no test pinned

**Front:** Round 49: test adequacy, mutation testing (Opus 5.5) | **Severity:** High | **Resolution:** Direct | **Round:** 49

mutmut over core/fs.py, core/naming.py and core/consistency.py, unsampled: 1474 mutants, 87.9% killed (91.1% without 32 equivalent and 20 Windows-only), each survivor confirmed against the full suite. Four High gaps where a plausible regression would pass the suite: the supersede check stopping at the first non-Superseded decision, the filename round-trip guard weakened (reproduced through the CLI: a title creating a name check then refuses), the scan stopping after an excluded file, and an unreadable decision hiding later numbers from init. The code was right; tests/test_behaviour_pins.py adopts 41 killing tests, and the no-hard-link fallback test now covers ENOTSUP and ENOSYS. The main weakness is assertions on error fields and input order, not message pinning (f57d438).
