# An older-form header with a damaged separator row was read as no header, so migrate could stack a second one

**Front:** Compatibility of existing repositories (round 50) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 50

parse_header reads a fields row whose first cell holds the label with more around it; has_header_shape matched only the exact form. With the separator row damaged, such a header was no-header, whose hint says to run migrate, and migrate put a new placeholder header on top and pushed the old one, with its status, into the body.

Decided by the project owner: has_header_shape reads the second line as parse_header does (no space at the cell's edges); only the second line, so a compact table lower in a note is not taken for a header.

Red: tests/test_header.py saw False. The first fix read all twelve lines; its adversarial control, |Custom Fields|Type| on line 5 of a note, came out a header, and the rule was narrowed to line 2. Class: every consumer (consistency, migrate, explore) calls this one function.
