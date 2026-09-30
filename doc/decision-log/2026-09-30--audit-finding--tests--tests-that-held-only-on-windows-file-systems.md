# Four tests of rounds 50-53 held only on Windows' file system

**Front:** Calibration (no dedicated audit front -- found by the first POSIX CI run since round 50) | **Severity:** Low | **Resolution:** Direct | **Round:** 53

Rounds 50-53 were verified on Windows only; the first CI run on ubuntu and macOS failed four tests, none of them a product defect. Two created a name with a lone surrogate, which only NTFS allows: skipped elsewhere, as round 51's own are. Round 52's test of the log's own pages still expected the case-sensitive rule round 53 replaced. Round 50's test of a user's index.md assumed a case-blind file system: on ext4 adrpy's INDEX.md sits beside it, the user's file untouched. All four fixed and run on ext4 (WSL, a venv as CI's) before the push: 2026 passed.
