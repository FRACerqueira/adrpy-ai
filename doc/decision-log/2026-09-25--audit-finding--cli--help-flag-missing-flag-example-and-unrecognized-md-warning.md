# --help after a command, a missing-flag example, a warning for digit-leading .md files, init serializes like config

**Front:** Round 44: real agent via claude -p | **Severity:** Low | **Resolution:** Direct | **Round:** 44

Agents in the runs tripped on small CLI gaps. adrpy <cmd> --help and -h answered usage-error; they are now adrpy help <cmd>, and the same in adrpy-skills. A missing required flag's usage-error shows an example (adrpy check --path .). check and explore warn, without failing, about .md files in folderadr whose name starts with a digit but is not an ADR name. init wrote the config with a different serializer than config, so the first config change rewrote unrelated lines; both use core/config.serialize_repo_config (8735a28).
