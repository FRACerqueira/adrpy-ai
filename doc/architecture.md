<img src="../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← README](../README.md)

# Architecture

This page explains how `adrpy-ai` is put together and why: the module
layout, the request lifecycle, the two load-bearing architectural
decisions (the repository lock and the install-level config), the
decision lifecycle the whole tool exists to manage, and -- as a separate
concern -- the `adrpy-skills` subsystem that ships alongside it in the
same distribution. For the individual command contracts, see
[`doc/commands/`](commands/INDEX.md); for the project's own recorded
architectural decisions and their full rationale, see [`doc/adr/`](adr/)
and [`doc/decision-log/`](decision-log/INDEX.md) -- this page summarizes
and links to them, it does not replace them.

## Why this project exists

`adrpy-ai` manages [Architecture Decision Records](https://adr.github.io/)
from the command line, built around three constraints stated directly in
its own package metadata and carried consistently through every command:

- **JSON in, JSON out, no wizard.** Every command is fully driven by
  flags and returns a single JSON object on stdout -- nothing waits for a
  keypress. This is not a UX preference; it is what makes the tool safe
  to script and safe for an AI agent to call without a human in the loop.
- **Self-documenting.** `adrpy help <command>` returns the exact same
  structured contract (arguments, types, failure codes) a human reads in
  `doc/commands/` -- the documentation and the code cannot silently drift
  apart, because the per-command pages in this repository are generated
  directly from that same `describe()` output, not written independently
  of it.
- **Zero runtime dependencies.** Every capability -- argument parsing,
  file locking, retry logic, per-OS path resolution -- is implemented in
  `core/` rather than pulled in from a package, so the tool has no
  supply-chain surface beyond the Python standard library.

`adrpy-ai` is also a Python companion to a reference tool, AdrPlus
(C#/.NET), by the same author -- see
[Relationship to AdrPlus](../README.md#relationship-to-adrplus) in the
main README for what that relationship does and does not mean. This page
only describes `adrpy-ai`'s own architecture.

## Module map

Every command handler in `cli/` is thin: it parses its own flags, then
delegates the actual work -- locking, reading, validating, writing -- to
the shared modules in `core/`. No `core/` module ever imports from `cli/`;
the dependency direction is one-way, always downward through these four
layers:

```mermaid
graph TD
    CALLER["Caller<br/>(human or AI agent)"] --> MAIN
    MAIN["__main__.py<br/>entry point + dispatch"] --> CLI
    CLI["cli/*.py<br/>14 thin command modules,<br/>one per adrpy verb"] --> CORE
    CORE["core/*.py<br/>16 shared modules, grouped by<br/>concern in the table below"] --> FS[("Filesystem")]
```

No single command uses every `core/` module -- Dispatch & contract's four
modules are the one exception, used by every command -- the table below is
the accurate picture; the diagram above is deliberately just the
layering, not a full edge list, because a command-by-module graph for 14
commands x 16 modules is a hairball no one can actually read.

| Concern | Modules | Responsibility |
|---|---|---|
| Dispatch & contract | `registry.py`, `args.py`, `output.py`, `errors.py` | Maps each verb to its command module; parses `--flag value` pairs; builds the JSON envelope and exit code; defines `CommandError`/`UsageError`. Used by every command. |
| Concurrency & storage | `lock.py`, `atomic_write.py`, `io_retry.py` | The whole-repository advisory lock ([ADR001](adr/ADR001V01-repository-lock-covers-the-full-critical-section-of-every-mutating-command.md)); atomic, retrying file writes; the shared transient-read-retry loop both of the above lean on. |
| Configuration | `config.py`, `install_config.py` | A repository's own `adr-config.adrplus` schema; the per-user install-level config ([ADR002](adr/ADR002V01-install-level-config-is-a-per-user-file-that-seeds-init-and-migrate-instead-of-an-install-directory-template.md)). |
| Decision file mechanics | `lifecycle.py`, `header.py`, `naming.py`, `casing.py`, `security.py` | Status transitions and family scans; the 12-line header format; filename parsing/building for both naming schemes; title case transforms; path-escape guards. |
| Decision log | `decision_log.py` | The mechanical half of a decision-log entry ([ADR003V01](adr/ADR003V01-decision-log-entries-separate-human-reviewed-judgment-from-tool-executed-mechanics-via-a-future-adrpy-log-command.md)): filename/structured-line construction, `Round` allocation, and `INDEX.md` regeneration -- judgment (classification, wording) stays outside the tool, in the [decision-log workflow](decision-log-workflow.md). Its own directory (`folderlog`) is independently configurable and recursively scanned, decoupled from `folderadr` ([ADR007V01](adr/ADR007V01-decision-log-directory-becomes-an-independent,-recursively-scanned-config-field-instead-of-a-fixed-sibling-of-folderadr.md), superseding ADR003V01's own schema driver). |
| Diagnostics | `warnings.py` | Builds the warning strings a result's `warnings` list carries for automatic, non-fatal recovery (a retried write, a reclaimed stale lock, orphan cleanup, an encoding repair), and each decision file left out of a family because its header does not parse ([lifecycle.md](lifecycle.md)). |

Every write command (`init`, `new`, `approve`, `reject`, `undo`,
`supersede`, `version`, `revise`, `migrate`, `config`, `installconfig`,
`log`) touches Concurrency &
storage; every command that reasons about existing decision files
touches Decision file mechanics; `init`/`config`/`migrate`/`installconfig`
touch Configuration; only `log` touches Decision log; every command
touches Dispatch & contract.

`core/` has one additional module not in this table: `hashing.py`, the
content-hash drift marker used exclusively by the separate `adrpy-skills`
entry point (see below) -- no `adrpy` command imports it, so it is
intentionally out of scope for this table.

## Request lifecycle

Every invocation follows the same shape, regardless of which command runs.
`__main__.py` is the single place that turns any exception -- a deliberate
`CommandError`, a malformed invocation, or a genuinely unexpected `OSError`
-- into the one JSON envelope every caller can rely on, so no command
module ever needs its own top-level `try`/`except` for that purpose.

```mermaid
sequenceDiagram
    participant Caller as Caller (human or AI agent)
    participant Main as __main__.main()
    participant Cmd as cli/*.py (per command)
    participant Core as core/* helpers
    participant FS as Filesystem

    Caller->>Main: adrpy new --path . --title "..."
    Main->>Main: look up verb in core/registry.py
    Main->>Cmd: command.run(args)
    Cmd->>Core: parse_flags(args, ...)
    Core-->>Cmd: validated values (or raises UsageError)
    Cmd->>Core: acquire_repo_lock(...)  -- mutating commands only
    Core->>FS: read config / decision files (post-lock, always fresh)
    FS-->>Core: current state
    Core-->>Cmd: validated, current data
    Cmd->>Core: atomic_write_text(...)  -- if a write is due
    Core->>FS: write temp file, then os.replace (atomic)
    Cmd-->>Main: result dict
    Main-->>Caller: success JSON envelope on stdout

    Note over Cmd,Main: A CommandError/UsageError/OSError raised anywhere<br/>in this path is caught once, in __main__.py, and<br/>turned into a failure JSON envelope instead
```

## Concurrency model

Every command that reads-then-writes shared repository state (`adr-config.adrplus`
or the decisions folder) acquires a single, whole-repository advisory lock
for its *entire* critical section -- not just the part that allocates a
number. This is [ADR001](adr/ADR001V01-repository-lock-covers-the-full-critical-section-of-every-mutating-command.md),
adopted after a reproduced defect showed the lock originally covered only
number allocation, letting two concurrent `approve`/`reject` calls on the
same file both report success with mutually exclusive outcomes.

```mermaid
sequenceDiagram
    participant A as Process A
    participant L as .adrpy.lock
    participant B as Process B

    A->>L: acquire_repo_lock() -- creates lock file with a token
    activate A
    Note over A: Re-reads config/target file INSIDE the lock<br/>(never trusts data captured before acquiring it)
    B->>L: acquire_repo_lock() -- blocks / polls
    A->>L: verify_still_held(token) -- pre-commit ownership recheck
    L-->>A: token still matches
    A->>L: atomic_write_text(...)
    A->>L: release
    deactivate A
    L-->>B: lock now free -- B acquires, repeats the same steps
```

If a lock holder is abandoned (crashed, or genuinely exceeds
`ABANDON_AFTER_SECONDS`), a waiting process reclaims it -- but the
original holder's own pre-commit ownership recheck then fails with a
distinct `lock-lost` error instead of writing, so a reclaim always
produces a clean, visible failure rather than a silent collision. `init`
is the one documented exception: a genuinely fresh `--path` (no config
yet) takes no lock at all, because the lock's own storage location does
not exist until that same call creates it -- see the ADR for why this is
an accepted, visibility-documented risk rather than an oversight.

## Configuration layering

`adrpy-ai` has two independent config scopes, and a defined precedence
between them, decided in [ADR002](adr/ADR002V01-install-level-config-is-a-per-user-file-that-seeds-init-and-migrate-instead-of-an-install-directory-template.md):

```mermaid
graph LR
    SEED["explicit --seed &lt;file&gt;"] -->|highest precedence| INIT
    INSTALL["per-user install-level config<br/>(adrpy installconfig)"] -->|used when no --seed| INIT["adrpy init"]
    BUILTIN["built-in default_repo_config.json"] -->|used when neither exists| INIT

    REPO["repository's own migrationpattern"] -->|used when non-empty| MIGRATE["adrpy migrate"]
    INSTALL2["per-user install-level config<br/>(adrpy installconfig)"] -->|fallback, and persisted back| MIGRATE
```

The install-level file lives at a per-user, OS-appropriate path
(`%APPDATA%\adrpy\install-config.json` on Windows,
`~/.config/adrpy/install-config.json` on Linux/macOS) -- deliberately
**not** relative to this package's own install directory, because writing
into a pip package's own install/site-packages directory is unsafe
(permissions, often shared, wiped on reinstall). Its schema is the same
full, seed-valid shape `init --seed` accepts, byte-compatible with a
repository's own `adr-config.adrplus` -- the one piece of schema
coherence this project deliberately keeps in step with the reference
tool, recorded in `core/config.py`'s own docstring.

## Decision lifecycle

Every decision file's three status cells (`status_create`,
`status_update`, and `status_change` for Superseded) move through a small,
fixed set of states, enforced by `core/lifecycle.py`'s own eligibility
checks (never inferred from a file's position on disk). The user-facing
rules -- what each command requires, the family rules, and the failure
code for each refusal -- are in [`lifecycle.md`](lifecycle.md):

```mermaid
stateDiagram-v2
    [*] --> Proposed: new
    Proposed --> Accepted: approve
    Proposed --> Rejected: reject
    Accepted --> Proposed: undo
    Rejected --> Proposed: undo
    Accepted --> Superseded: supersede
    Superseded --> [*]

    note right of Superseded
        supersede also creates a new
        decision, status Proposed, under
        the next free sequence number
        (a new family), whose filename's
        supersede suffix points back here
    end note

    note right of Accepted
        version / revise never change
        this file's own status -- they
        branch a new family member,
        status Proposed, from an
        Accepted or Rejected source
    end note
```

A **family** is every file sharing the same leading sequence number
(`ADR001*`): `version` starts a new major version and `revise` a new
wording-fix revision -- both create a new Proposed sibling in the same
family rather than mutating the source they branch from. `supersede`
instead creates a Proposed successor under a new sequence number (a new
family), writing it before marking the predecessor `Superseded`. `reject`
on a successor also reverts its predecessor's `Superseded` status back
(predecessor first), undoing the `supersede` that created it, in the
same two-write operation.

## The `adrpy-skills` subsystem

`adrpy-skills` is a second, independent console-script entry point in the
same distribution (`pip install adrpy-ai` installs both `adrpy` and
`adrpy-skills` on `PATH`) -- installing AI-coding-agent skill files, not
managing ADRs. See [ADR009V01](adr/ADR009V01-ai-coding-agent-skills-installer-ships-as-a-separate-adrpy-skills-entry-point-with-per-provider-full-body-or-stub-delivery.md)
for why it exists as a separate entry point rather than an `adrpy`
subcommand: `adrpy` manages the ADR/decision-log *record* mechanically and
must stay pure -- this feature installs *operating instructions for an AI
agent*, a different concern, for more than one provider (Claude Code,
Cursor, GitHub Copilot, generic `AGENTS.md`) with genuinely different
activation models, which the reference tool has no equivalent of at all.
`adrpy`'s own command surface never mentions `adrpy-skills`; installing or
running it is entirely opt-in.

### Module map

```mermaid
graph TD
    CALLER2["Caller<br/>(human or AI agent)"] --> MAIN2
    MAIN2["skills/__main__.py<br/>entry point + dispatch"] --> REG2
    REG2["skills/registry.py<br/>verb -> command module"] --> CMD2
    CMD2["skills/commands/*.py<br/>4 thin command modules:<br/>help, install, remove, list"] --> INSTALLER
    INSTALLER["skills/installer.py<br/>drift-state detection + write/delete<br/>orchestration per (provider, skill)"] --> PROVIDERS
    INSTALLER --> RESOURCES
    PROVIDERS["skills/providers.py<br/>per-provider path + content-wrap table"]
    RESOURCES["skills/resources.py<br/>loads gate.md/body.md/glue.md<br/>from packaged skill resources"]
    INSTALLER --> CORESHARED
    CORESHARED["core/atomic_write.py, core/hashing.py,<br/>core/io_retry.py, core/warnings.py<br/>(reused from adrpy's own core/)"] --> FS2[("Filesystem<br/>(target repo, or ~/.claude etc. for --target global)")]
```

| Module | Responsibility |
|---|---|
| `skills/__main__.py` | Entry point + dispatch: looks up the verb in `skills/registry.py`, handles `--version`/`-v` and `--help`/`-h` (the one JSON-exception convenience, mirroring `adrpy/__main__.py`), and is the single place any exception becomes the JSON envelope. |
| `skills/registry.py` | Maps each of the 4 verbs (`help`, `install`, `remove`, `list`) to its command module -- a separate table from `core/registry.py`'s own, by design (ADR009V01: never touches `adrpy`'s own command surface). |
| `skills/commands/*.py` | 4 thin command modules, one per verb: each owns its own `describe()` contract and flag parsing (`core/args.parse_flags`, reused from `adrpy`), then delegates to `skills/installer.py`. |
| `skills/installer.py` | The shared mechanics: content generation per (provider, skill), `foreign`/`drifted`/`malformed` classification, and the actual write/delete orchestration for `install`/`remove`/`list`. |
| `skills/providers.py` | The provider-adapter table (ADR009V01): per-provider project/global file path, delivery mode (`full`/`stub`/`stub_block`), and the wrap function shaping content for that provider. |
| `skills/resources.py` | Loads each bundled skill's static `gate.md`/`body.md`/`glue.md`/`meta.json` from the package and assembles the full content a `claude`/`cursor` provider gets, or the one shared doc a stub-mode provider points at. |

`skills/installer.py` also reuses `core/atomic_write.py`, `core/hashing.py`
(the content-hash drift marker), `core/io_retry.py` (transient-read
retries), and `core/warnings.py` from `adrpy`'s own `core/` -- but never
`core/lock.py` or `core/lifecycle.py`: there is no repository-wide lock
and no decision-file concept here at all (see "Request flow" below).

### Request flow

Genuinely different from `adrpy`'s own request lifecycle, not a variant of it:

```mermaid
sequenceDiagram
    participant Caller as Caller (human or AI agent)
    participant Main as skills/__main__.main()
    participant Cmd as skills/commands/*.py (per command)
    participant Inst as skills/installer.py
    participant Prov as skills/providers.py
    participant FS as Filesystem

    Caller->>Main: adrpy-skills install --skill decision-log --provider claude
    Main->>Main: look up verb in skills/registry.py
    Main->>Cmd: command.run(args)
    Cmd->>Cmd: parse_flags(args, ...) -- reuses core/args.py
    Cmd->>Inst: install(providers, skills, target, path, force)
    Inst->>FS: remove orphaned <name>.<uuid4>.tmp next to each target path (older than 30s)
    Inst->>Prov: resolve file path + wrap content for this provider
    Inst->>FS: read existing file (core/io_retry.py) to classify drift state
    FS-->>Inst: current content, or none
    Inst->>Inst: classify clean / foreign / drifted / malformed
    Inst->>FS: atomic_write_text(...) -- only when clean, or --force given
    Cmd-->>Main: result dict (shape is per-command: installed/skipped,<br/>removed/skipped, or a skills cross-product -- not one shared shape)
    Main-->>Caller: success JSON envelope on stdout

    Note over Cmd,Main: No repository lock: adrpy-skills never acquires<br/>core/lock.py's whole-repository lock, and has no<br/>core/lifecycle.py concept of a "decision file" at all --<br/>each write is its own, narrower critical section.
```

Unlike `adrpy`'s single `{data.decisions, data.warnings, ...}`-shaped
envelope, `adrpy-skills`' `data` shape differs by command -- `install`
returns `{installed, skipped, warnings}`, `remove` returns `{removed,
skipped, warnings}`, `list` returns `{skills, warnings}` (a cross-product
of every requested skill x provider), and `help` returns `{commands}`
(plus a `hint` on the bare listing) with no `warnings` key at all (a read-only listing command with
nothing to report omits the key rather than sending an empty list).

## The JSON contract

Every command returns exactly one JSON object on stdout, whether it
succeeds or fails:

```json
{"success": true, "data": {"...": "..."}, "warnings": []}
```

```json
{"success": false, "code": "repository-locked", "detail": "...", "data": {"...": "..."}, "warnings": []}
```

`code` is always a stable, documented string (`repository-locked`,
`config-already-exists`, ...), never a free-text message a caller has to
pattern-match -- the full, per-command list of codes lives inline in each
command's own [`doc/commands/`](commands/INDEX.md) page, next to the
exact condition that triggers it. `warnings` is always present, even when
empty, on every `adrpy` command's response -- see the `adrpy-skills`
subsystem section above for how that entry point's own envelope differs.
`warnings` carries non-fatal information about automatic recovery a
command's own dependencies performed silently (a retried write, a
reclaimed stale lock, orphaned temp-file cleanup, an encoding repair), and
every decision file a command left out because its header does not parse --
information that would otherwise be discarded before it ever reached
anywhere a caller could see it.

A failure also carries `detail`, a human-readable explanation (which
flag, which file, what to do next), whenever one exists
([ADR010](adr/ADR010V01-failure-responses-carry-a-human-readable-detail-in-the-stdout-json,-with-stderr-kept-as-a-copy-outside-the-contract.md)).
It is for people: decide on `code` and `data`, never by parsing
`detail`, whose wording may change in any release. The same text is
also written to stderr, so it stays visible in a terminal while stdout
is piped elsewhere -- that copy is a convenience outside the contract,
and nothing may depend on it.

## Where to go deeper

- [`doc/commands/`](commands/INDEX.md) -- full argument and failure-code
  reference, one page per command, generated from `describe()`.
- [`doc/skills/`](skills/README.md) -- how `adrpy-skills` installs the
  judgment layer for AI coding agents, per provider.
- [`doc/adr/`](adr/) -- this project's own formal Architecture Decision
  Records, written using `adrpy-ai` itself.
- [`doc/decision-log/`](decision-log/INDEX.md) -- confirmed divergences
  from the reference tool, audit findings, and deferred/accepted
  trade-offs that did not rise to a full ADR.
- [`doc/decision-log-workflow.md`](decision-log-workflow.md) -- how to
  decide between an ADR and a decision-log entry, and how to write either.
- [README's own "Relationship to AdrPlus"](../README.md#relationship-to-adrplus)
  -- what this project shares with, and deliberately does not share with,
  its reference tool.
