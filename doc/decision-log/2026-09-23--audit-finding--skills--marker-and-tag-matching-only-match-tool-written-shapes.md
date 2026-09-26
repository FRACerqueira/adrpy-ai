# Marker and AGENTS.md tag matching now only match what the tool itself writes

**Front:** Round 38: hash-marker, filesystem-security and test-adequacy fronts | **Severity:** Low | **Resolution:** Direct | **Round:** 38

Two related fixes, both in 426e342.
- core/hashing.py: the optional lazy frontmatter group backtracked past the first closing `---`, over later `---` rule lines, to a marker-shaped comment mid-body. A hand-written file then read as drifted, or as clean with a crafted hash, instead of foreign. Frontmatter is now matched on its own, up to the first closing `---` (the boundary _insert_marker uses), and the marker is required exactly there or at position 0.
- installer.py: _AGENTSMD_TAG_RE now matches only a whole line, as the block template writes it. A tag quoted inside the user's prose made the block malformed, and --force then stripped it out of the user's sentence. What is newly excluded: a tag sharing its line with other text, so a hand-edit that joins a start tag to the next line now reads malformed instead of clean. Still treated as a tag: one alone on its line inside a code fence.
