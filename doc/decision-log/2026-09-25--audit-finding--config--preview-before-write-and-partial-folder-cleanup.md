# config computes the migrationpattern preview before writing, and a folder it cannot finish creating leaves none of its parents

**Front:** Round 45: resilience of the Round 44 additions | **Severity:** Low | **Resolution:** Direct | **Round:** 45

The migrationpattern preview ran after the config was written, so a Ctrl+C there answered interrupted with no data while the config had changed; it now runs inside the guarded block, before the write. A mkdir that created the parents and then failed on the folder itself left them behind, because the folder was recorded only after make_dirs returned and remove_created_dirs stopped at the folder that never existed; make_dirs now undoes itself and remove_created_dirs skips a missing folder. The first red test hit the wrong mkdir and was fixed before the code (572c5c7).
