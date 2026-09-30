# The shipped decision-log skill said CYCLES.md may be renamed, which makes adrpy log refuse

**Front:** Documentation versus code (round 51 confirmation) | **Severity:** Medium | **Resolution:** Direct | **Round:** 51

src/adrpy/resources/skills/decision-log/body.md said a project may rename CYCLES.md; core/decision_log.py exempts exactly INDEX.md and CYCLES.md, so any other .md there makes log refuse (log-directory-contains-unrecognized-file), run and confirmed. Fix: the skill says the name is exactly CYCLES.md and that log refuses any other .md file there.
