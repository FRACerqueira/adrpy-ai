# migrate processed the files in the order the folder lists them, so its results depended on the filesystem

**Front:** Calibration (no dedicated audit front -- found via CI on Linux and macOS after the Round 46 push) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 46

migrate took its candidates in scan_tree's order, which is the folder's listing order: by name on NTFS and APFS, in hash order on ext4. The order of the results, and which files an interrupt leaves migrated, differed between systems; CI on Linux showed it (4 tests assumed 0001 before 0002). The candidates are now sorted by their path relative to the decisions folder, by name (the owner's choice over number order; unpadded numbers sort as text, the same on every system). Red then green with a test that reverses the listing.
