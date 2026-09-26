# Writing a decision that is a file symlink replaces the link with a regular file

**Reopen-when:** Round 49 runs, or a user reports a decision that is a symlink

prepare_write puts the temp next to the path given and commit_write os.replace()s it onto that path, so when the decision is a file symlink the link itself becomes a regular file with the new content and the real file stays unchanged, while the command reports success. Found by reading the code in Round 48's independent pre-commit review; not reproduced here (creating symlinks needs a privilege this Windows machine lacks). It predates Round 48. Deferred to Round 49 by the owner, where a POSIX run can reproduce it; the likely fix writes to the resolved path or refuses a symlinked decision.
