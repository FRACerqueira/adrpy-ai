# adrpy-skills CLI ergonomics: flags named in errors, --path must exist, --target global defaults to claude

**Front:** Round 38: usability and stability fronts | **Severity:** Low | **Resolution:** Direct | **Round:** 38

Low findings from the Round 38 fronts, fixed red/green in f4724d9:
- --target now tolerates surrounding spaces like --provider/--skill.
- Unknown or empty --provider/--skill values now name their flag and are reported together in one usage-error.
- `help <unknown>` is unknown-command, as in adrpy's own help.
- A --path that doesn't exist is refused with target-directory-not-found by install, remove and list in project scope, instead of install creating the whole tree.
- --target global with --provider omitted means every provider with a global scope (claude), instead of always failing; an explicit `-p all -t global` suggests `--provider claude`.
- The orphan-cleanup warning names each file relative to the target.
- remove warns when it keeps a shared doc that another stub still uses.
f4724d9 was committed with test_every_command_documents_usage_error failing: help's usage-error code had been replaced instead of kept alongside unknown-command, and the suite result was piped through tail so its exit code went unchecked. 71aedeb fixed it.
