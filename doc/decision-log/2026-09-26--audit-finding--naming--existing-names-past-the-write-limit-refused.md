# An existing name past the 234 bytes the tool can rewrite is refused before writing, and check warns about it

**Front:** Round 48: R47 boundaries (Opus 5.5 and Fable 5.1) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 48

Resolves 2026-09-26--deferred--naming--existing-names-past-the-write-limit.md, whose reopen condition both passes met: such a name passed check but every rewrite failed with a raw Errno 22, supersede reported the successor although the predecessor failed, and migrate could never migrate such a legacy name. The owner chose both: approve, reject, undo and supersede (and reject's predecessor) refuse it with filename-too-long and a rename-by-hand remedy keeping number, version, revision and --NNN; migrate reports it for that file and migrates the rest; check warns about such names. The review found the check also refused version and revise, which never rewrite --file; it now applies only to the commands that do (208e32a).
