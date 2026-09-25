# The read-back that decides what was written retries a transient permission error, and a second Ctrl+C during it keeps what was already counted

**Front:** Round 45: resilience of the Round 44 additions | **Severity:** Medium | **Resolution:** Escalated | **Round:** 45

write_landed treated any OSError as not written, so a transient PermissionError (antivirus, indexer) on the file just renamed onto made supersede report a written predecessor as pending, with a repair hint that would break the repository. It now reads back with read_with_permission_retry. A second Ctrl+C during the read-back escaped the handler and lost all data (migrate lost every migrated result); owner decision (option B): inside the failure handlers only, it leaves that one file unconfirmed and the handler still reports what it had counted. Red then green in tests/test_interrupt_after_commit.py (572c5c7).
