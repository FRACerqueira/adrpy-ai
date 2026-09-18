# Short-flag aliases are now documented in describe()

**Front:** Usability (round 7), Finding 4 | **Severity:** Low | **Resolution:** Direct

Round 7 usability audit, Finding 4: every command's real `parse_flags(aliases=...)` accepts a short form (`-p`, `-f`, `-t`, ...), but `describe()` never exposed it anywhere -- an agent relying solely on `describe()`/`help` (the documented self-description channel for a non-interactive caller) had no way to discover these forms exist. The schema already tolerates non-standard argument metadata (`help.py`'s own `"positional"` key) -- this is an inconsistency in what the project chooses to expose, not a hard schema limitation.

**Fix**: added an `"alias"` key to every affected argument across `new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`, `migrate`, `init`, and `explore`, following the same schema-extension convention `help.py` already established.
