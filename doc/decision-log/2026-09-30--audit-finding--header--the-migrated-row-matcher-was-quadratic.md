# The migrated fields row's pattern took over a second on a long note row, every command

**Front:** Header recognition and the user's own files (round 53 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 53

The backtracking pattern cost 1.4 s per file on a 16 KB table row of short words ending in a comment, read by every command's validation. It is now a linear check, the same answer on 772,206 generated rows. Its second opinion found the folded comparison sliced the unfolded text (`|a|ß <!-- s -->|` read as a migrated row) and that a headermigrated holding `<!--`, still accepted from a `--seed`, was no longer matched: the boundary is now found in the folded text, and init --seed and installconfig --seed refuse `<!--` and `-->` in headerdisclaimer and headermigrated as the field flags do. The INVALID_HEADER hint also names a compact `|Fields|Values|` table.
