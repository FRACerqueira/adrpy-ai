# the shipped decision-log skill now uses date-first names and a closed classification set, as adrpy log enforces

**Front:** Round 43: contract and docs of the new surfaces | **Severity:** Medium | **Resolution:** Escalated | **Round:** 43

The skill adrpy-skills installs told agents to name entries classification-first and allowed new classifications, while adrpy log writes date-first and refuses unknown classifications; an agent following it broke every later log call. Owner decision: fix the shipped copy only (src/adrpy/resources/skills/decision-log); the global skill stays classification-first, a local deviation. Lock-era examples replaced; doc/decision-log-workflow.md and glue.md agree again. Fixed in c7331d0.
