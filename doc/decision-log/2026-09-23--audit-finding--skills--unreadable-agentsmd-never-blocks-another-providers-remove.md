# An unreadable AGENTS.md no longer blocks another provider's remove

**Front:** Round 38: re-verification front (B3-3), decided by the project owner | **Severity:** Low | **Resolution:** Escalated | **Round:** 38

With an AGENTS.md that isn't valid UTF-8 or is over the read limit, remove -p copilot deleted the stub and then failed while checking whether AGENTS.md still pointed at the shared doc. Every retry failed until the unrelated file was re-saved. e6aee00: that check treats an unreadable AGENTS.md as still referencing the doc, so the doc is kept, one warning says why, and the call succeeds. Removing agentsmd itself still fails on such a file (positive control), because its block can't be removed safely.
