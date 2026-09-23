# migrate's lock-lost failure reports the fallback pattern it had already written

**Front:** Round 38: multi-write recoverability front | **Severity:** Low | **Resolution:** Direct | **Round:** 38

When migrate fell back to the install-level migrationpattern, wrote it into adr-config.adrplus, and then lost the lock before any candidate, migration-lock-lost reported only results: []. That reads as 'nothing written', although the config write had committed. f00a377: data carries migrationpattern_persisted whenever that persist-back happened. Red: the key was missing.
