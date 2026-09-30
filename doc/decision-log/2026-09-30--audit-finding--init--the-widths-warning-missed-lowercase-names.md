# init's other-widths warning missed names adrpy reads case-blind, such as adr001v01-a.md

**Front:** Compatibility of existing repositories (round 51 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 51

The warning's name pattern was case-sensitive while core/naming reads the prefix, V and R case-blind. Fix: re.I. Red then green in tests/test_init.py; the second opinion confirmed silence for correct widths in any case.
