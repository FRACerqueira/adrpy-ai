# An agent wrote migrationpattern believing config previewed it and left check failing; explore --migrationpattern now previews without writing

**Front:** Round 45: real agent via claude -p (revalidation batches 1-5) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 45

In batch 2, S5b ran config --migrationpattern described as a preview, found it read a meeting note as decision 2024, stopped, and left the repository failing check with three no-header errors without telling the user; check's warning said config's result 'previews', and no preview without writing existed. Owner decision: explore --path . --migrationpattern <pattern> returns the same preview and writes nothing (byte-compared); config and check now say config writes the config, and the skill says to clear it and tell the user when stopping (572c5c7).
