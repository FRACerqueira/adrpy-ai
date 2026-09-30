# An entry named .MD counted on Windows and not on POSIX, so Rounds could go backwards across systems

**Front:** Decisions index and decision log (round 53 confirmation) | **Severity:** Low | **Resolution:** Escalated | **Round:** 53

The log's scan matched `.md` by the system's rule: on POSIX `x.MD` was left out of Round allocation and the index, on Windows counted. The owner chose to read the decision log's `.md`, and its own INDEX.md and CYCLES.md, in any case on every system; the decisions folder keeps the system's rule. Red is not reachable on Windows, where the old rule already folds case: the tests are red on POSIX CI.
