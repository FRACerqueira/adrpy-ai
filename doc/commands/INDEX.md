<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← README](../../README.md) · [Architecture](../architecture.md)

# Command Reference

One page per `adrpy` command, each generated directly from that command's own
`describe()` contract -- the same JSON `adrpy help <command>` returns at
runtime. If a page here and the CLI ever disagree, the CLI is right and the
page has drifted; regenerate it instead of hand-editing around the gap.

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
| [`config`](config.md) | Reads or updates an existing repository's own `adr-config.adrplus`. |
| [`installconfig`](installconfig.md) | Reads or updates the per-user, install-level default config (seeds new repositories, supplies a `migrate` fallback). |
| [`log`](log.md) | Writes a decision-log entry -- the lighter-weight sibling of a formal ADR. |

Every failure code a command can return is documented on that command's
own page, in its `## Failure codes` table (ADR008V01) -- the same
structured `failure_codes` field `adrpy help <command>` returns at
runtime, not free-form prose. There is still no separate GLOBAL
error-code index: codes genuinely specific to one command's own
operation are only ever listed there, since a code's meaning is only
complete together with the specific write it guards. Codes with
identical meaning everywhere they're reachable (config-schema
validation, header parsing) are authored once, in a shared source next
to the code that raises them, and merged into every command's own table
that can actually return them -- still delivered on that command's own
page, never referenced from outside it. This claim is checkable by an
automated test
(`tests/test_help.py::test_every_failure_code_is_documented_somewhere`).
