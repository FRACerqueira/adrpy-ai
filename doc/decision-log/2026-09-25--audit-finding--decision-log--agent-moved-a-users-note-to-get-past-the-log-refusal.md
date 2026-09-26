# An agent moved a user's note out of the log folder to get past the refusal; check now warns and the refusal says the file is the user's

**Front:** Round 46: real-agent breadth (claude -p; opus-5-5, sonnet-5, haiku-4-5; 4 batches) | **Severity:** High | **Resolution:** Escalated | **Round:** 46

In batch 1 haiku moved a meeting note into the decision-log folder without asking; in batch 3 (S11) haiku moved a note OUT of it to get the entry written and answered only 'Done'. The log refusal read 'cannot ... while this file is present', which invites removing it. check and explore now warn about any file in folderlog that is not an entry (the same recognition log uses), and the refusal and the warning say it was not written by adrpy, is the user's, and to ask where it belongs, never delete it. Batch 4: 0/6 moves across the three models; no S11 run loaded the adrpy skill, so the credit is the CLI text (0be5f3b).
