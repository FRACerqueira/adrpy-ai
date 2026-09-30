# Command examples named files the default sizes never create, and revise's example described revisions as off

**Front:** Documentation versus code (round 50) | **Severity:** Medium | **Resolution:** Direct | **Round:** 50

Six hand-written examples in doc/commands/ ran against ADR0001V01-..., which new never creates under the defaults: run as written, approve answered file-not-found. revise.md said revisions are off by default, ran a no-op config --lenrevision 2 and promised R01, where revise creates R02; config.md's one-field example was that same no-op; doc/lifecycle.md presented revisions as opt-in, and three filename examples (the skill, lifecycle.md, architecture.md) had no revision.

Fix: every example uses ADR0001V01R01-...; revise's says it creates R02 and when it refuses; config's changes headerscope. Checked by running each page's example as written in a fresh repository: every one succeeds. Class: grep postgre-sql and revision wording over doc/, README and the skill.
