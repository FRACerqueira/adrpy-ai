# adrpy-skills install/remove now sweep orphaned temp files, like the 8 core mutating commands

**Front:** Round 37: stability front | **Severity:** Low | **Resolution:** Direct | **Round:** 37

The stability front found adrpy-skills never cleaned up temp files orphaned by an interrupted atomic_write_text (a killed process, a full disk), unlike every core mutating command. 901c201 added the sweep at the start of install()/remove(). That fix swept far too broadly -- the whole project target and all of ~/.claude/skills -- and deleted the user's own *.tmp files; see 2026-09-23--audit-finding--skills--orphan-sweep-deleted-users-own-tmp-files.md for the regression and its fix.
