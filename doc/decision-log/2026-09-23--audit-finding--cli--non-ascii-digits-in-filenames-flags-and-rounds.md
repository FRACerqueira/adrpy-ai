# filenames, migrationpattern, integer flags and Round values accept only ASCII digits

**Front:** Round 41: test-adequacy front | **Severity:** Medium | **Resolution:** Direct | **Round:** 41

The test-adequacy front found the filename pattern's \d without re.ASCII: ADR followed by Arabic-Indic digits read as number 1, version 2 and collided with ADR001V02 -- the filename decides identity. Class closed in 075cb80: _ADR_PATTERN and _MIGRATION_PATTERN compile with re.ASCII; core/args.plain_int (ASCII digits, optional leading '-') backs config/installconfig integer fields, log --round and the Round read from existing entries (int() also accepted other scripts' digits, '+4' and '4_0'). Red/green for each site.
