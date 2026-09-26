# The interrupt-after-commit tests never exercised the POSIX exclusive create

**Front:** Calibration (no dedicated audit front -- found via CI on Linux and macOS after the Round 46 push) | **Severity:** Low | **Resolution:** Direct | **Round:** 46

tests/test_interrupt_after_commit.py injected the interrupt only into os.replace and os.rename. On POSIX an exclusive create (supersede's successor, a log entry) is os.link, so those interrupts never fired there and 3 tests failed on macOS and Linux. The helpers now also intercept os.link; the file passes on Windows and under a simulated POSIX path (_IS_WINDOWS False).
