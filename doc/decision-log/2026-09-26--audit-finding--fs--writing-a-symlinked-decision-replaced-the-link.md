# Writing a decision that is a symbolic link replaced the link and reported success

**Front:** Round 49: R48 changes and the symlink target (Fable 5.1) | **Severity:** High | **Resolution:** Escalated | **Round:** 49

Resolves 2026-09-26--deferred--fs--writing-through-a-file-symlink-replaces-the-link.md, reproduced on POSIX (WSL): approve, reject, undo and supersede through a file symlink turned the link into a regular file holding the new state, left the real decision unchanged, reported success, and left the repository inconsistent (duplicate-number); migrate did the same through a .md link to a non-.md file. The owner chose to refuse and warn: target-is-a-link from the commands that rewrite --file and for reject's predecessor, migrate reports it for that file, and check warns about every .md link in the decisions folder and, since the review, about a candidate excluded for leading out of the repository. Red then green on POSIX (f57d438).
