# config left the decisions index stale after a label or folderadr change

**Front:** Resilience of the INDEX.md write path (round 50) | **Severity:** Low | **Resolution:** Escalated | **Round:** 50

config was not one of the index's writers: a header label change showed only at the next decision write, and a folderadr change left the old index behind, never updated again.

Decided by the project owner (regenerate at config, or accept and document): config regenerates the index after every field write, and names the previous folder's generated index, which it never deletes. Recorded in ADR0013's revision.

Red then green: two tests in tests/test_adr_index.py.
