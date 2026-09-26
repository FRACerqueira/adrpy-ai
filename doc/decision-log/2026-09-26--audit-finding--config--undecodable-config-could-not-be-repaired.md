# installconfig could no longer repair a config json.loads cannot finish decoding (a Round 47 regression)

**Front:** Round 48: R47 boundaries (Opus 5.5) | **Severity:** Medium | **Resolution:** Direct | **Round:** 48

Round 47's replaced-values warning parses the current install-level config before replacing it, catching only CommandError and OSError; parse_repo_config mapped only JSONDecodeError. A file nested past the recursion limit, or holding an integer past Python's digit limit, then made installconfig --seed/--language fail with internal-error and leave the file as it was; before Round 47 they replaced it. parse_repo_config now maps ValueError and RecursionError from json.loads to config-invalid-json, which closes the regression and the same internal-error in every command that loads a config. Red then green (208e32a).
