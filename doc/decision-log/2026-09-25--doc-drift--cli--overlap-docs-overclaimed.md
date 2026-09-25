# Overclaims in the overlap docs: can be corrected, read twice, range after T

**Front:** Round 46: independent pre-commit reviews | **Severity:** Low | **Resolution:** Direct | **Round:** 46

config.md, migrate.md, config's describe and the CHANGELOG said an overlapping pattern 'can be corrected', which is false once a decision was migrated with it (the guard keeps it), and that 'no character may be read twice', while a range placed after T is not checked. The texts now say only what the check does and when the pattern can change (0be5f3b).
