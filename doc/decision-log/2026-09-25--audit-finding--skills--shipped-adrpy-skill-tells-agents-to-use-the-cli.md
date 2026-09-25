# No shipped skill told an agent the adrpy CLI exists; adrpy-skills now ships an adrpy skill

**Front:** Round 44: real agent via claude -p (S3) | **Severity:** High | **Resolution:** Escalated | **Round:** 44

In the real-agent run S3 a fresh agent, with only what adrpy-skills installs, renamed a successor with git mv and dropped its --001 suffix, breaking the supersede link, and told the user the suffix was a revision. Nothing installed said the CLI exists, that check comes first, or that ADR files are never renamed. Owner decision: ship a short adrpy skill (check first and follow each hint, never rename or hand-write a decision, what --NNN means, one line per command). The owner also removed comment-audit from what adrpy-skills ships; a RETIRED_SKILL_NAMES path keeps remove and list working for an older install, and ADR009's text no longer lists it (8735a28).
