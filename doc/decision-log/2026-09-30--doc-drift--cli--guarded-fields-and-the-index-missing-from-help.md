# help, the skill and lifecycle.md left headertablefields out of the guarded fields and never mentioned the generated index

**Front:** Documentation versus code (round 50) | **Severity:** Medium | **Resolution:** Direct | **Round:** 50

headertablefields is guarded, but config's and init's describe() and doc/lifecycle.md listed the guarded fields without it. No writer's describe(), nor the adrpy skill agents read, said that <folderadr>/INDEX.md is regenerated, and the skill told an agent to list the files that do not look like decisions, which includes the index; explore's texts said it lists every .md file.

Fix: the guarded lists name headertablefields; each of the ten writers' describe() says it regenerates the index and that a failure or a user's INDEX.md is a warning; explore's texts except the generated index; the skill has a rule never to edit, move or delete it. doc/commands/ regenerated from describe(); tests/test_command_docs.py passes.
