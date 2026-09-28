# parse_repo_config's comment promised a repair init and config cannot make

**Front:** Round 49: R48 changes and the symlink target (Fable 5.1) | **Severity:** Low | **Resolution:** Escalated | **Round:** 49

Round 48's comment said mapping undecodable JSON to config-invalid-json lets the commands that replace the whole file repair it; that holds for installconfig --seed/--language, but init --seed and config read the current file to run their change guards and fail the same way. The owner chose to fix the comment and have config-invalid-json's detail say to repair the file by hand (naming installconfig for the install-level config) (f57d438).
