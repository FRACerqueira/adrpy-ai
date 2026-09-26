# orphan temp files of the config, INDEX.md and install config are swept; a refused config no longer recreates folderadr

**Front:** Round 43: crash resilience | **Severity:** Low | **Resolution:** Direct | **Round:** 43

After a kill before the replace, adr-config.adrplus.<hex>.tmp (at the repository root, a git add . candidate), INDEX.md.<hex>.tmp and install-config.json.<hex>.tmp were never removed, contradicting the README. config, init, migrate, log and installconfig now sweep them with the same 30 s own-name rule. config created folderadr before any validation, so a refused call recreated it; the folder is now created only where the guards need it and removed if a guard refuses. Red/green. Fixed in c7331d0.
