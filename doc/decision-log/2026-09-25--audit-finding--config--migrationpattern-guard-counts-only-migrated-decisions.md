# A wrong migrationpattern locked itself; the guard counts only migrated decisions, with a preview and misread warnings

**Front:** Round 44: real agent via claude -p (S5) | **Severity:** High | **Resolution:** Escalated | **Round:** 44

In S5 the agent set a wrong migrationpattern and could then neither change nor clear it: the guard counted headerless legacy files the pattern merely matched by name. Owner decision: only a legacy decision with a valid header blocks the change. config --migrationpattern now returns migrationpattern_preview, migrate warns when a title starts with the separator or a number is far above the others, and describe() explains the syntax with 'N00:04T05' for 0001-title.md and points to explore as the preview. init --seed applies the same rule (8735a28).
