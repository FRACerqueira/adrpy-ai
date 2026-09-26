# The agent approved decisions nobody asked to accept; the adrpy skill now does only the lifecycle actions asked

**Front:** Round 45: real agent via claude -p (revalidation batches 1-5) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 45

In batch 1 the agent ran approve after supersede in S2 and S2b ('the user stated it as decided') and approved two migrated decisions in S5b, although no prompt asked to accept; the skill only pointed to the decision-log gate, which no run loaded. Owner decision: a rule in the adrpy skill itself -- creating, versioning, revising, superseding or migrating does not accept; approve, reject and undo only when asked, or ask first. Batches 2-5: no unasked approve (572c5c7).
