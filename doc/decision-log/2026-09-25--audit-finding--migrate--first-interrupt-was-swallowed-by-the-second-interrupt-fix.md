# The first fix for a second Ctrl+C swallowed the user's first one in migrate's per-file path; the catch now lives only in the failure handlers

**Front:** Round 45: independent pre-commit review | **Severity:** Medium | **Resolution:** Direct | **Round:** 45

Catching KeyboardInterrupt inside write_landed also caught it where write_landed runs outside any interrupt handler: migrate's per-file path after a replace that raised. The user's first Ctrl+C there was taken as not written and migrate went on with the next files. write_landed catches only OSError again; core/fs.landed_after_failure, used only inside the four handlers that already end the command, carries the second-interrupt behaviour. Red: migration-write-failed with the next file migrated; green: interrupted, next file untouched (572c5c7).
