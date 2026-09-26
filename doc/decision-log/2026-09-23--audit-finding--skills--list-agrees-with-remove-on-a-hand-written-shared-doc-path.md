# list agrees with remove on a hand-written file at the shared-doc path

**Front:** Round 38: re-verification front (B3-4), decided by the project owner | **Severity:** Low | **Resolution:** Escalated | **Round:** 38

list reported a user-written doc/ai-skills/<name>.md with no marker and no stub as shared-doc installed/drifted, while remove correctly treats it as out of scope since 586fe34. e4e2167: list uses the same rule, so such a file is reported as not installed. With a stub pointing at it, it is still reported installed and drifted, which is what install would refuse to overwrite (positive control).
