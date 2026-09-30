# A file with an adrpy header but another prefix or separator was ignored silently, and new reused its number

**Front:** Compatibility of existing repositories (round 51 confirmation) | **Severity:** Low | **Resolution:** Escalated | **Round:** 51

check and explore said nothing about a DEC0001V01R01-a.md or ADR0001V01R01_a.md with a valid adrpy header: no rule sees it, and new created ADR0001 next to it.

Decided by the project owner (warn, or keep the rule that a .md without an ADR name is ignored): check and explore name such files. The second opinion on the first version found the cost (check opened every unrecognized .md: 0.4 s to 23 s on 5,000 freshly written notes, the CI case) and advice that could not be followed (config refuses a prefix or separator change while decisions exist or would be adopted; renaming without a free number duplicates one). Fix: only names shaped like a decision's (digits, V, digits) are opened, the digit rule matches the older warning's exactly, and the text says to rename by hand to a free number. Red then green in tests/test_check.py (a note is never opened; the advice).
