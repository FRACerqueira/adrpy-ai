# The per-command sweep tests planted only the 32-hex temp shape the tool no longer writes

**Front:** Round 48: R47 boundaries (Fable 5.1) | **Severity:** Low | **Resolution:** Direct | **Round:** 48

tests/test_orphan_temp_sweeps.py built its orphans with a full uuid4 hex, so the config, init, log, migrate and installconfig sweeps were never exercised with the 16-hex shape Round 47 introduced (only unit tests covered it). The helper now plants the current shape; the 32-hex form stays covered by the unit tests (208e32a).
