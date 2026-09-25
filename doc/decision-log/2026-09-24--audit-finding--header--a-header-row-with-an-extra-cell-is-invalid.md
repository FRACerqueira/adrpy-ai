# a header row with an extra cell separator is invalid instead of silently dropping the extra text

**Front:** Round 43: validator vs specification (independent oracle, Fable) | **Severity:** Medium | **Resolution:** Direct | **Round:** 43

header._extract_cell read only between the 2nd and 3rd '|', so '|File title md|a|b|' validated and 'b' was dropped; the spec lists such a title as invalid-header. Title/scope/domain rows now fail with field-contains-forbidden-character, other rows with their own *-not-found code. Also: a file with merge-conflict markers no longer triggers derived errors on its neighbours, and invalid-status-combination carries a detail. Red/green. Fixed in c7331d0.
