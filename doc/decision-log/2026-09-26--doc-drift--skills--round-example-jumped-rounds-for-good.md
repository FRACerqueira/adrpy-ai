# The decision-log skill's --round example jumped the round for good instead of reusing it

**Front:** Round 48: documentation vs code | **Severity:** Medium | **Resolution:** Direct | **Round:** 48

glue.md and doc/decision-log-workflow.md said 'a second finding in that SAME round: pass --round explicitly to reuse it' and passed --round 12 right after an example that auto-assigns Round 1. Run as written it recorded Round 12, and rounds never go down; an agent copying it would skip rounds permanently. The example now passes the number the first call's warning named (1) and says why (208e32a).
