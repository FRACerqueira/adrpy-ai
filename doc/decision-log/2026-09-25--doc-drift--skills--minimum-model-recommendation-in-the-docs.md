# A minimum-model recommendation in the documentation, from three Claude models; other providers untested

**Front:** Round 46: real-agent breadth (claude -p; opus-5-5, sonnet-5, haiku-4-5; 4 batches) | **Severity:** Low | **Resolution:** Escalated | **Round:** 46

Owner decision: the recommendation lives in the documentation, not in the skill. doc/skills/README.md 'Which model to use' gives what each Claude model did over the batches and recommends a model at least as capable as Claude Sonnet 5 for tasks that write decisions; Cursor, GitHub Copilot and AGENTS.md were not tested with a real agent and must be tested before relying on them. README points to it (0be5f3b).
