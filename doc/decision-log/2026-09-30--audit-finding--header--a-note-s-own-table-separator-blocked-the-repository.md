# A note's own table with an exact separator row read as a damaged header and blocked the repository

**Front:** Compatibility of existing repositories (round 51 confirmation, escalated) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 51

An exact `|--|--|` anywhere in the first 12 lines counted as the header's mark, so a decision-named note or legacy file whose own table used that separator read as a damaged header: check reported invalid-header and migrate refused the whole run. The owner chose to stop taking a note's table for a header. The separator now counts only on the first line, where no table can have it; the other marks (see the formatter entry of the same day) cover a damaged header without it. A file opening with its own key-value table whose rows are named like the header's is no header either.
