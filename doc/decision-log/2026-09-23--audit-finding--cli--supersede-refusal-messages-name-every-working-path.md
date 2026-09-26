# supersede's refusal messages name the working path for every blocked state

**Front:** Round 38: re-verification of the supersede --resume change | **Severity:** Low | **Resolution:** Direct | **Round:** 38

The Round 38 re-verification front found that supersede-successor-already-exists advice led nowhere in two states:
- a successor itself superseded since, which can't be undone or rejected until its own successor is rejected (that reverts it);
- a successor in a family with version/revision siblings, which reject can't handle until --resume has run.
The front confirmed each working path. 53e2343 names them in the message and in describe().

Architectural review (Round 43): the refusal this entry reworded, `supersede-successor-already-exists`, and the `--resume` it pointed to were removed. The states it described are validator errors now (`successor-without-predecessor`, `multiple-live-successors`, `superseded-not-live`), each with its repair hint in `core/consistency.HINTS`.
