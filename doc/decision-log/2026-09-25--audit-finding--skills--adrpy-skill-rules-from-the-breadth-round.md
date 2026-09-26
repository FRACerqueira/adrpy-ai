# Skill rules from the real-agent runs: supersede for a replacement, migrated decisions have no status, review after creating, keep placeholders, relay warnings, ask before swapping a refused pattern, never move a user's file

**Front:** Round 46: real-agent breadth (claude -p; opus-5-5, sonnet-5, haiku-4-5; 4 batches) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 46

Batch 1 showed gaps that held across models: a described replacement created with new, a migrated decision reported as 'Accepted', no review request after only creating a decision, the justification placeholder dropped, warnings not relayed, and a refused user-given pattern swapped silently. The adrpy skill gained one rule for each, plus 'never move, rename or delete a file adrpy did not write to get past a refusal' and a clause that nothing needs asking when every file is a decision. Precision on S1-S10b, batch 1 -> batch 3: opus 44/44 -> 44/44, sonnet 37/44 -> 44/44, haiku 29/43 -> 33/41 (0be5f3b).
