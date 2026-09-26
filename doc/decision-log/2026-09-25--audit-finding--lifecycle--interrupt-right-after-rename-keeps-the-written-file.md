# A Ctrl+C right after the rename no longer loses a written file

**Front:** Round 44: resilience of the Round 43 additions | **Severity:** Medium | **Resolution:** Direct | **Round:** 44

A KeyboardInterrupt delivered right after os.replace/os.rename returned (still inside commit_write) made supersede, reject, log and migrate report a file on disk as not written (KeyError 'data', a predecessor listed as pending, migrate results == []). One mechanism now decides it from the disk: a prepared write keeps its size and sha256, and core/fs.write_landed counts a step as applied when the target's bytes match. Red: 7 tests in tests/test_interrupt_after_commit.py failed as predicted; green after the fix, plus a test that an interrupt before the entry lands does not name it (8735a28).
