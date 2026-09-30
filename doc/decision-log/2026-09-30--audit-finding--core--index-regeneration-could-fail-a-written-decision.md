# Regenerating the decisions index could turn a written decision into a failed command

**Front:** Resilience of the INDEX.md write path (round 50) | **Severity:** Medium | **Resolution:** Direct | **Round:** 50

adr_index.regenerate caught only OSError and CommandError. A decision in a folder whose name holds a lone surrogate (valid on NTFS) made quote() and the UTF-8 encode raise UnicodeEncodeError after the decision was written: new and approve answered internal-error, exit 1, with the file on disk. migrate re-read the config for the index outside every wrapper, so a failure there turned a finished migration into io-error and dropped data.results.

Fix: regenerate turns any Exception into a warning; the link is quoted with surrogateescape; migrate passes a loader, so the re-read runs inside the same guard.

Red: tests/test_adr_index.py raised ValueError, UnicodeEncodeError (a real surrogate folder on Windows) and PermissionError (migrate). Green after. Class: grep adr_index.regenerate in src matched 10 call sites in 9 files; all go through the one handler.
