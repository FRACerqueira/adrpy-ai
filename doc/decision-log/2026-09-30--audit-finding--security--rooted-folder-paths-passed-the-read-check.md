# A rooted folderadr or folderlog with no drive, or one escaping only on POSIX, passed the read-time check

**Front:** Compatibility of existing repositories (round 50) | **Severity:** Low | **Resolution:** Direct | **Round:** 50

_is_relative_path missed a leading backslash (rooted at the current drive on Windows): \x and \.. passed, and check ran with folderlog \.. until log refused it. _stays_inside read the value with Windows separators only, so a\b/../../x, which escapes on POSIX where \ is part of a name, passed. resolve_within still stopped every use, so nothing escaped.

Fix: a leading backslash is refused, and the depth is checked in both readings. Red then green in tests/test_config.py, with a\b/../c as the positive control that stays inside both ways.
