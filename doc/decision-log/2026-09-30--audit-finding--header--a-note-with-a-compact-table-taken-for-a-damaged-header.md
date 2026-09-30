# A note whose second line is a compact table holding the fields label was taken for a damaged header

**Front:** Compatibility of existing repositories (round 51 confirmation) | **Severity:** Medium | **Resolution:** Retraction | **Round:** 51

Round 50 read line 2 in the older form (the label inside the first cell) with no condition on line 1. A note with a heading and then |Custom Fields|Meaning| became invalid-header: before adoption migrate refused the whole run, after adoption every lifecycle command was blocked with a hint about a header the note never had. The second opinion on the fix found the same with an ordinary comment first (<!-- toc -->, <!-- markdownlint-disable -->).

Fix: the older form counts only under the comment every header opens with, ending in its line range ((1-12) -->). Red then green in tests/test_header.py and tests/test_check.py (an adopted repository with such a note: check counts 1 decision and new writes). The rule is strictly narrower than before, so it adds no false positive; accepted as Low, an older-form header with TWO faults (line 1 and the separator) now reads as no header.
