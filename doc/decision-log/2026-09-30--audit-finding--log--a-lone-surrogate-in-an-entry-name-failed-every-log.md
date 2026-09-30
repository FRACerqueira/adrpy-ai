# A lone surrogate in a hand-placed entry's name made every later log fail to write its index

**Front:** Decisions index and decision log (round 52) | **Severity:** Medium | **Resolution:** Direct | **Round:** 52

The log index wrote names as they are, so a name NTFS allows but UTF-8 cannot hold raised on the write: every later `adrpy log` wrote its entry and answered log-index-regeneration-failed, the index frozen. Round 51 fixed the same in the decisions index only. Each cell now shows such a character as U+FFFD, and the link target is quoted with surrogatepass.
