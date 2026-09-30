# A lone surrogate outside U+DC80-U+DCFF, in a folder or a legacy file name, froze the index

**Front:** Resilience of the INDEX.md write path (round 51 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 51

surrogateescape only maps U+DC80-U+DCFF: a folder named with U+D800 made every index write fail, and the second opinion found the same with a legacy file name, whose stem is the link text. Fix: links are quoted with surrogatepass and the link text shows a lone surrogate as U+FFFD, so the page is written; that one link cannot be exact. Red then green in tests/test_adr_index.py (Windows).
