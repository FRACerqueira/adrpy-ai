# The forbidden-character constraint is now documented on new/supersede/version's own title/domain/scope arguments

**Front:** Usability (round 7), Finding 1 | **Severity:** Medium | **Resolution:** Direct | **Round:** 7

Round 7 usability audit, Finding 1: `reject_embedded_delimiter` (core/security.py) is enforced on title/domain/scope in `new`, and domain/scope in `supersede`/`version`, but only `config.py`'s own field descriptions ever mentioned this constraint -- an asymmetry the codebase's own comments draw the analogy for but never actually documented on the live-command side. An agent following only the stated domain of these fields had no way to learn `field-contains-forbidden-character` exists short of triggering it.

**Fix**: `new`/`supersede`/`version`'s affected argument descriptions now state the constraint and its error code, matching `config.py`'s own existing wording.
