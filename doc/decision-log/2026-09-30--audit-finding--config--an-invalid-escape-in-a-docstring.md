# A docstring written in round 50 held an invalid escape, a warning now and an error in a later Python

**Front:** Second opinion on a round 51 fix (compiling the tree) | **Severity:** Low | **Resolution:** Direct | **Round:** 51

_is_relative_path's docstring had a backslash before a backtick: SyntaxWarning on compile, SyntaxError under -W error. Fix: the text says backslash. Class: tests/test_header.py now compiles every file under src/adrpy with warnings as errors; it failed on this line before the fix and passes after.
