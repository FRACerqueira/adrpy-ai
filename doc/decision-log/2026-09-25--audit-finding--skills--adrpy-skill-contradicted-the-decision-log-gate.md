# The adrpy skill's pointer to the decision-log gate contradicted its own rules, and the command map was incomplete

**Front:** Round 46: documentation audit (docs vs code, skill vs CLI, model guidance vs reports, ADRs) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 46

The adrpy gate said the decision-log approval gate applies before any write, while the body tells an agent to apply check's first repair option without asking and to go ahead with a migrate the user asked for; the pointer now covers recording a new decision or entry. The command map left out that supersede, version and revise accept a migrated placeholder; also the --NNN exception for migration-successor-files-exist, hand repair when a command's warning says so, and the decision-log gate listing --severity and doc-drift. Revalidated with real agents on S3, S4, S7 and S10: 12/12 correct across three models (b5649f4).
