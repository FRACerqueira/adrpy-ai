# Log index cells and links broke on odd names, a Round below 1 was accepted, and folderlog changes named no old page

**Front:** Decisions index and decision log (round 52) | **Severity:** Low | **Resolution:** Direct | **Round:** 52

A `|` in a heading or a Round cell shifted the row's columns, and a link target with spaces or `]` was not a link: cells escape `|` (a backslash is left as written, which a code span shows as is), link text escapes `\`, `[` and `]`, and targets are quoted. A Round of 0 or below on an entry made log allocate 0 and then refuse its own advice; it now fails closed as malformed. The log's own INDEX.md and CYCLES.md are compared as the file system compares names (Cycles.md on Windows is the page, not a stray). A folderlog change names the generated index the previous folder keeps, comparing the folders as the file system resolves them (the same folder spelled another way is none).
