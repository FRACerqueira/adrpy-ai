# the POSIX no-hard-link fallback reserves the name with O_EXCL, then os.replace, so a crash never leaves a truncated decision

**Front:** Round 43: crash resilience | **Severity:** Medium | **Resolution:** Direct | **Round:** 43

The crash-resilience front simulated POSIX without hard links and killed version mid-copy: ADR001V02 kept 64 KiB of 308 KiB and adrpy check passed; a later sweep then removed the only complete temp. _copy_exclusive now creates the target empty with O_CREAT|O_EXCL (the reservation refuses an existing name), closes it, and os.replace's the complete temp onto it; a crash leaves at most an empty file, which the validator reports as no-header. Red/green in tests/test_fs.py. Fixed in c7331d0.
