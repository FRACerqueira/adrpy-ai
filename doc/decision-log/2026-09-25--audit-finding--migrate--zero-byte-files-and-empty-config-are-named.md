# 0-byte files from an interrupted create are named by check and skipped by migrate; an empty config gets config-file-empty

**Front:** Round 44: resilience of the Round 43 additions | **Severity:** Low | **Resolution:** Direct | **Round:** 44

An interrupted create can leave a 0-byte reservation. check reported it as no-header with no detail and migrate gave it a header; with only such files migrate migrated them. Now check's detail says '0-byte file (most likely left by an interrupted create).', the no-header hint gains the remove-it branch, and migrate skips 0-byte files with a warning. The pre-commit review found a file holding only a BOM was also taken as 0-byte; the decision uses the real size (core/fs.is_zero_bytes), so a BOM-only file behaves as before. A 0-byte adr-config.adrplus now fails with config-file-empty on init and every command that loads it (8735a28).
