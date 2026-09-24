<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← README](../../README.md) · [Decision lifecycle](../lifecycle.md) · [Architecture](../architecture.md)

# Command Reference

One page per `adrpy` command. The Description, Arguments and Failure codes
sections of every page are generated from that command's own `describe()`
contract -- the same JSON `adrpy help <command>` returns at runtime -- by
`scripts/generate_command_docs.py`; only the summary line and the Example
section are written by hand. `tests/test_command_docs.py` fails when a page
differs from what `describe()` renders, or when a command has no page: after
changing a command's contract, run the script instead of editing the page.

| Command | Purpose |
|---|---|
| [`help`](help.md) | Lists every command, or describes one of them in full. |
| [`init`](init.md) | Initializes an ADR repository: writes `adr-config.adrplus` and creates the decisions folder. |
| [`new`](new.md) | Creates a new decision, status `Proposed`. |
| [`approve`](approve.md) | Marks a `Proposed` decision `Accepted`. |
| [`reject`](reject.md) | Marks a `Proposed` decision `Rejected`. |
| [`undo`](undo.md) | Reverts a decision's `Accepted`/`Rejected` status back to `Proposed`. |
| [`supersede`](supersede.md) | Marks an `Accepted` decision `Superseded` and creates its successor. |
| [`version`](version.md) | Creates a new major version of an `Accepted`/`Rejected` decision. |
| [`revise`](revise.md) | Creates a new revision (wording fix) of an `Accepted`/`Rejected` decision. |
| [`migrate`](migrate.md) | Adds an adrpy-compliant header to existing, hand-written decision files. |
| [`explore`](explore.md) | Lists every decision file in the repository, on a best-effort basis. |
| [`check`](check.md) | Validates every decision in the repository and lists every inconsistency found. |
| [`config`](config.md) | Reads or updates an existing repository's own `adr-config.adrplus`. |
| [`installconfig`](installconfig.md) | Reads or updates the per-user, install-level default config (seeds new repositories, supplies a `migrate` fallback). |
| [`log`](log.md) | Writes a decision-log entry -- the lighter-weight sibling of a formal ADR. |

Every failure code a command can return is listed on that command's own
page, in its `## Failure codes` table (ADR008V01) -- the structured
`failure_codes` field of `describe()`, not prose. There is no separate
global error-code index: codes with the same meaning everywhere they are
reachable (config-schema validation, header parsing, the repository
validation) are authored once, next to the code that raises them, and
merged into the table of every command that can return them.
`tests/test_help.py::test_every_failure_code_is_documented_somewhere`
checks that every code appears in at least one command's table; whether
each table lists every code its own command can return is kept by review.

Five codes any command can return are not repeated on every page: `usage-error` (a malformed invocation, exit code 2), `unknown-command`, `io-error` (an OS error no more specific code covers), `interrupted` (Ctrl+C) and `internal-error` (a genuinely unexpected exception). `interrupted` carries `data` when the command had already written something: `migrate` once it has persisted a fallback migrationpattern or started migrating files (`data.migrationpattern_persisted`, `data.results`, possibly empty); `supersede` and `reject` after their first file (`data.applied`, `data.pending`, `data.repair`, as for `multi-file-write-partially-applied`); `log` after the entry, before `INDEX.md` (`data.file`).
