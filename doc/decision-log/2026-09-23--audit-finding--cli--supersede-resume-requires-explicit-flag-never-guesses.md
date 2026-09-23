# supersede never resumes onto an existing successor unless --resume is given, and refuses what it can't verify

**Front:** Round 38: supersede state-consistency, doc-drift and multi-write recoverability fronts (independently corroborated) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 38

The automatic resume from 2026-09-23--audit-finding--cli--supersede-writes-successor-first-and-resumes-on-retry.md could not tell an interrupted supersede from a normal supersede, reject-successor, undo sequence, which is identical on disk. It resumed with no failure at all, dropped --title/--scope/--domain silently, and warned falsely. It also resumed a migrated placeholder with no Created status, and accepted a --refdate earlier than the successor's creation. The project owner chose option B, 'refuse instead of guessing'. Implemented in 78938e4:
- Without --resume, any existing non-Rejected successor pointing back is refused with the new supersede-successor-already-exists.
- --resume resumes only onto exactly one successor that is still Proposed with its own Created status and date. It refuses an earlier --refdate (refdate-before-history), and cannot be combined with --title/--scope/--domain (usage-error).
- A file pointing back whose header can't be read is named in data.file.
At round close, 29e02ac made the refusal messages name the step that works for a successor approved since (undo first; neither reject nor --resume accepts an Accepted one), proven by a test.
