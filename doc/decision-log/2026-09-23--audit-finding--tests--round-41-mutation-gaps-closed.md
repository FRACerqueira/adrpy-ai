# the Round 40 guards now have tests that fail when a guard is removed

**Front:** Round 41: test-adequacy front | **Severity:** High | **Resolution:** Direct | **Round:** 41

107 mutants over the Round 40 code, 38 survivors. The serious gaps: deleting the lock check from approve or reject (migrated placeholders, where it is the only guard) or the rejected-successor check from revise left the suite green. Closed in 075cb80 with about 20 tests: the lock on migrated V01/V02 and R01/R02 placeholders, revise of a rejected successor, the fall-through to newer revisions, the positive control of a newer version not locked by an older version's higher revision, latest_file naming the highest revision, revise numbering from filenames, the ASCII-digit checks at every site, and tightened assertions (a revise test that accepted any result). Spot check: removing either guard now fails the suite.
