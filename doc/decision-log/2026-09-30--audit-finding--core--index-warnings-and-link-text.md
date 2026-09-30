# The index left invalid decisions out silently, promised the next write would fix it, and collapsed legacy link text

**Front:** Resilience of the INDEX.md write path (round 50) | **Severity:** Low | **Resolution:** Direct | **Round:** 50

Three gaps in the index's own output. init, which does not validate first, wrote an index without the decisions whose header does not parse, and said nothing. The failure warning said the next write updates it, false when the obstacle is permanent (a folder or junction named INDEX.md). A legacy prefix holding the separator (ADR-0001-...) gave every row the link text ADR.

Fix: render names the decisions left out (the invalid-header errors of the same check, so a file with no header yet before migrate is not named); the warning says the next command that writes a decision tries again; a legacy name keeps its whole stem as link text.

Red then green: three tests in tests/test_adr_index.py. The first version of the left-out warning also named files with no header yet; test_a_right_migrationpattern_previews_without_warnings caught it, and the check now reads the errors' codes.
