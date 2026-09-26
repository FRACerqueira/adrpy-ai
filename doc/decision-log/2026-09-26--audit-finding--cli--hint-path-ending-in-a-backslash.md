# A hint's quoted path ending in a backslash left an unterminated command in bash

**Front:** Round 49: R48 changes and the symlink target (Fable 5.1) | **Severity:** Low | **Resolution:** Escalated | **Round:** 49

shell_argument double-quoted a path such as `C:\\repo\\` as-is, and bash reads the backslash before the closing quote as escaping it. The owner chose to drop trailing backslashes when the path means the same without them, and to show the placeholder for a root (`C:\\`, a lone backslash). Red then green (f57d438).
