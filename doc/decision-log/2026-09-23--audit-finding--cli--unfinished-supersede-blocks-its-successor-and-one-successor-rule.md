# an unfinished supersede's successor can't move on until resumed, and one rule decides what a successor is

**Front:** Round 41: pre-commit re-verification | **Severity:** Medium | **Resolution:** Escalated | **Round:** 41

K2a, decided by the owner, fixed in 8c2f673: approve, version and revise refuse any member of the family of an interrupted supersede's successor (its predecessor does not point at it) with supersede-not-finished, naming the successor and the predecessor number; reject and undo still work. It closes a pre-existing path where an approved, evolved orphan left two live lines. The re-verification then found three rules treating any --NNN suffix as a successor, trapping hand-made files with a same- or lower-number suffix; is_successor (a suffix and a higher number, as doc/lifecycle.md defines) now gates the rejected-successor rule, the unfinished-supersede rule and reject's predecessor revert.

Architectural review (Round 43): `supersede-not-finished` was removed. An unfinished supersede's successor (no predecessor pointing back) is now the validator error `successor-without-predecessor`, and every lifecycle action refuses the whole repository until it is repaired by hand: a stricter form of the same rule. `is_successor` (a suffix naming a lower number) is still the one successor rule, now in `core/family.py`, used by the validator and by reject.
