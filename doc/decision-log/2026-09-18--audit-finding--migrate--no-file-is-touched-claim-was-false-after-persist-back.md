# migrate's "no file is touched" claim was false for adr-config.adrplus after a persist-back

**Front:** Usability | **Severity:** Medium | **Resolution:** Direct | **Round:** 11

The persist-back write (fallback `migrationpattern` written into the repo's own `adr-config.adrplus`) happens before the scan/eligibility checks, with no rollback. Every failure path after it (`migration-scan-failed`/`-incomplete`/`-unreliable-encoding`, `no-decisions-found`, `already-tool-created-adrs-exist`, `no-eligible-files-to-migrate`) fires with `adr-config.adrplus` already durably rewritten, even though `describe()` said "no file is touched." Separately, `describe()` described the persist-back as "part of the same locked write" as the migration, reading as atomic-with-it, when it's actually a distinct, earlier `atomic_write_text` call that commits independently and survives any later failure in the same run.

**Fix:** rewrote both claims precisely -- the persist-back is now described as an earlier, independent write inside the same lock, and "no file is touched" scoped to decision files specifically. adrpy-ai `278f5b4`. New describe()-text assertion test.

**Open, not decided here:** whether the persist-back write should instead be deferred until after the eligibility checks succeed, so a refused run genuinely touches nothing -- escalated to the project owner, not resolved by this doc fix.
