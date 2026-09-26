# remove's deletes now retry a transient PermissionError, like reads and writes already did

**Front:** Round 38: stability front | **Severity:** Medium | **Resolution:** Direct | **Round:** 38

remove's two unlink calls had no retry, while reads and writes absorb a transient PermissionError such as an editor, agent or antivirus scanner briefly holding the file (WinError 32). f3fc0ab adds _unlink_with_retry, which uses atomic_write_bytes' own budget and exponential backoff and re-raises once exhausted. The read side's flat 3x50ms budget still left 23/60 failing, so it was not reused. Measured with 3 concurrent list readers pausing 1ms over 60 cycles: 40/60 removes failed before, 0/60 after. Under zero-pause (continuous) contention 17/60 still fail; that is now reported with partial effects.
