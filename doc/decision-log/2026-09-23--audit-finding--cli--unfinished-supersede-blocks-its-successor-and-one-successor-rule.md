# an unfinished supersede's successor can't move on until resumed, and one rule decides what a successor is

**Front:** Round 41: pre-commit re-verification | **Severity:** Medium | **Resolution:** Escalated | **Round:** 41

K2a, decided by the owner, fixed in 8c2f673: approve, version and revise refuse any member of the family of an interrupted supersede's successor (its predecessor does not point at it) with supersede-not-finished, naming the successor and the predecessor number; reject and undo still work. It closes a pre-existing path where an approved, evolved orphan left two live lines. The re-verification then found three rules treating any --NNN suffix as a successor, trapping hand-made files with a same- or lower-number suffix; is_successor (a suffix and a higher number, as doc/lifecycle.md defines) now gates the rejected-successor rule, the unfinished-supersede rule and reject's predecessor revert.
