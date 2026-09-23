# explain() never blank, log warns on a stale index, migrate always reports what it persisted and migrated

**Front:** Round 39: narrow re-verification and pre-commit reviews | **Severity:** Low | **Resolution:** Direct | **Round:** 39

Fixed in 2e5854f: explain() falls back to the exception's type name (and errno) instead of an empty detail, and keeps both filenames; it is used for detail, warnings and migrate's per-file errors (R9a, C8). log warns when INDEX.md could not be regenerated on the already-exists path (R10a). migrate carries migrationpattern_persisted on success, on every failure it reports, and on an interrupt after the persist-back, with the warnings already collected (R11a, P4a, C7); an unexpected internal-error does not. Fixed in b4d6d4c: an interrupt once files are being migrated names the ones already migrated in data.results (N3a). Red/green for each.
