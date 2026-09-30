# ADR0008 said no command-docs generator exists and ADR0009 called glue.md a verbatim copy

**Front:** Documentation versus code, running the examples (round 53 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 53

ADR0008V01R00 said doc/commands stays hand-maintained with no generator; scripts/generate_command_docs.py and its drift test exist since 2026-09-24. ADR0009V01R00 said glue.md reuses doc/decision-log-workflow.md verbatim; it is adapted (links as plain names, wording specific to this repository generalized). The owner authorized editing those body sentences by hand, the decisions unchanged: they now say what held then and what holds since. Their stale counts (FailureCodes, commands) were left as written.
