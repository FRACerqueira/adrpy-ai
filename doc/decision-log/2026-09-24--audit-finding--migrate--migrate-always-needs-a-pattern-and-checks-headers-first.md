# migrate always requires migrationpattern (now documented), checks tool-created headers first, and config can clear the pattern

**Front:** Round 43: validator vs specification (independent oracle, Fable) and Round 43: contract and docs of the new surfaces | **Severity:** Medium | **Resolution:** Escalated | **Round:** 43

The no-header hint said to run migrate, which then refused with migration-pattern-not-configured even when every name already followed the current scheme (any valid pattern unblocked it). Owner decisions: migrate always requires a migrationpattern, documented in the hint, README and lifecycle.md; already-tool-created-adrs-exist is checked before the pattern, with data.files; config accepts --migrationpattern "" to clear it under the same legacy guard (ADR002V01 note). Red/green. Fixed in c7331d0.
