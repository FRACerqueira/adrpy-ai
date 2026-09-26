# A BOM an editor added no longer turns a tool-written file foreign

**Front:** Round 38: hash-marker front (BOM ownership, decided by the project owner) | **Severity:** Low | **Resolution:** Escalated | **Round:** 38

A BOM prepended by an editor to a SKILL.md, .mdc or .instructions.md the tool wrote hid the marker's position, so the file read as foreign: blocked, and mislabelled. The project owner chose to ignore it. 20fe1eb: check_drift strips a leading BOM, which the tool never writes. A real edit behind the BOM still reads drifted (tested). AGENTS.md is unaffected, because check_drift only sees a block's inner text there; the tag matching already tolerates a start-of-file BOM (720d3b8).
