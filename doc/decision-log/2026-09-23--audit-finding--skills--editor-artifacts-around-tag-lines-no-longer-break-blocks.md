# A BOM, trailing spaces or indentation around an AGENTS.md tag line no longer break a tool-written block

**Front:** Round 38: re-verification of the C7 tag anchoring | **Severity:** Medium | **Resolution:** Direct | **Round:** 38

Regression from 426e342 (marker-and-tag-matching-only-match-tool-written-shapes), found by the Round 38 re-verification front. Anchoring tags to whole lines had three effects:
- A BOM at the very start of AGENTS.md (from an editor, or PowerShell 5.1 -Encoding UTF8) turned a tool-written block malformed, and install --force then appended a second copy, duplicating the instructions agents read.
- A trailing space after a tag broke recognition.
- An indented tag read as absent, so install appended a duplicate.
Fixed in 720d3b8: the tag regex tolerates surrounding spaces/tabs and a start-of-file BOM, kept outside the match so a rewrite preserves it. A tag quoted mid-line is still not a tag. Red: malformed, 2 copies after --force, and blocks not recognized. Also fixed: an AGENTS.md reference to the shared doc written with backslashes now counts, so remove no longer deletes a doc that text still names.
