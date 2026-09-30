# A user's own INDEX.md in the decisions or decision-log folder was overwritten without a warning

**Front:** Resilience, compatibility and docs-vs-code passes, independently (round 50) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 50

adr_index.regenerate and decision_log.regenerate_index replaced INDEX.md unconditionally. init on an existing folder, the adoption path, replaced a hand-kept index; on Windows a lowercase index.md too. It contradicted the rule that a file adrpy did not write is the user's.

Decided by the project owner among three options (overwrite only a file carrying the generated line; back it up; reserve the name): a file without the generated line is left as it is, with a warning saying to rename or move it to have the index. Both indexes use fs.written_by_someone_else. Recorded in ADR0013's revision.

Red: tests/test_adr_index.py and tests/test_log.py saw the user's text replaced. Green after.
