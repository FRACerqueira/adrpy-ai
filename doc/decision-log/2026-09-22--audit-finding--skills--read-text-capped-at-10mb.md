# installer.py's _read_text now caps reads at 10MB instead of loading any file whole

**Front:** Round 37: filesystem-security front | **Severity:** Medium | **Resolution:** Direct | **Round:** 37

The filesystem-security front measured _read_text reading a 100MB file whole (about 200MB peak memory). It was the only full-content reader in the project without a size cap; core/config.py (64KB) and core/lock.py (4KB) already bound theirs, and explore closed the same class in round 26. _read_text now reads in bounded chunks and raises OSError past 10MB (2c4c75f), larger than config.py's cap because AGENTS.md and skill content are user-authored documents with no schema bound. Red/green tests for over-the-cap and at-the-cap files.
