<img src="https://raw.githubusercontent.com/FRACerqueira/adrpy-ai/main/src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

# adrpy-ai

[![CI](https://github.com/FRACerqueira/adrpy-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/FRACerqueira/adrpy-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/FRACerqueira/adrpy-ai/blob/main/LICENSE)

**ADR lifecycle CLI for humans and AI agents alike — JSON-only, no wizard, zero dependencies.**

adrpy-ai manages [Architecture Decision Records](https://adr.github.io/) (ADRs) from the command line: create, approve, reject, undo, supersede, version, and revise decisions, check that a repository is consistent, and migrate legacy hand-written files into the tool's own format. Every command takes flags in and returns JSON out — no interactive prompts, ever — so it works identically whether you're typing it yourself or an AI coding agent is driving it through a shell tool.

adrpy-ai is the reference implementation of the ADR lifecycle it shares with [AdrPlus](https://github.com/FRACerqueira/AdrPlus) (C#/.NET), also by Fernando Cerqueira: AdrPlus will follow adrpy's rules, and adrpy reads AdrPlus 1.0.0 repositories as they are. See [Relationship to AdrPlus](#relationship-to-adrplus) below.

## Table of Contents

- [Why adrpy-ai](#why-adrpy-ai)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [Checking a repository (`adrpy check`)](#checking-a-repository-adrpy-check)
- [One owner per working copy](#one-owner-per-working-copy)
- [Using adrpy-ai with AI Coding Agents](#using-adrpy-ai-with-ai-coding-agents)
- [Installing the judgment layer (`adrpy-skills`)](#installing-the-judgment-layer-adrpy-skills)
- [Configuration](#configuration)
- [Relationship to AdrPlus](#relationship-to-adrplus)
- [Adopting adrpy on an AdrPlus 1.0.0 repository](#adopting-adrpy-on-an-adrplus-100-repository)
- [Architecture and Design Decisions](#architecture-and-design-decisions)
- [Contributing](#contributing)
- [License](#license)

## Why adrpy-ai

- **No wizard, ever.** Every command is fully driven by flags. Nothing waits for a keypress, so it's safe to script and safe for an agent to call without a human in the loop.
- **JSON in, JSON out.** Every response is a single JSON object on stdout (`{"success": true/false, "data"/"code": ...}`), with a fixed, documented set of failure codes per command — no output your own tooling has to guess the shape of. A failure also carries `detail`, a human-readable explanation to show a person; decide on `code`/`data`, not on `detail`'s wording. The same text is copied to stderr for terminal use, outside the contract. The exit code is 0 on success, 1 on a failure and 2 on a malformed call (`usage-error`, `unknown-command`). The one exception to JSON is `--version` (`adrpy --version`, `adrpy-skills --version`), which prints plain text for a person.
- **Self-documenting.** `adrpy help <command>` returns the exact same structured contract (arguments, types, failure codes) this README describes — the documentation and the code can't silently drift apart, because they're the same artifact.
- **Zero runtime dependencies.** `pip install adrpy-ai` (or install from source) pulls in nothing else.
- **A full lifecycle, not just file creation.** `init`, `new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`, `migrate`, `check`, `config`, `installconfig` — the whole decision lifecycle, not a one-shot generator.
- **Validates before acting.** Every lifecycle command (`new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`) first validates the whole repository — headers, numbering, family and supersede rules — and, if anything is broken, lists every problem with a repair hint and changes nothing. `adrpy check` runs the same validation on its own, for a pre-commit hook or CI. See [`doc/lifecycle.md`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/lifecycle.md).
- **One owner per working copy.** adrpy does no locking: git coordinates people, and one person (or agent) at a time runs adrpy on a given working copy. Each file write is atomic and a new file is never created over an existing one; beyond that, the tool detects an inconsistent repository and reports it, it does not prevent one. See [One owner per working copy](#one-owner-per-working-copy).

## Installation

```bash
pip install adrpy-ai
adrpy help
```

Requires Python 3.11+. The package is `adrpy-ai`; `ADRpy` on PyPI is an unrelated project. Don't install both in the same environment: on Windows and macOS their import folders (`adrpy` and `ADRpy`) are the same folder, and their files mix.

To install from source instead — for development, or to run a specific commit:

```bash
git clone https://github.com/FRACerqueira/adrpy-ai.git
cd adrpy-ai
pip install .
adrpy help
```

The source install needs a git clone: the version is read from git, so a folder from GitHub's "Download ZIP" does not install. On Windows, some file names under `doc/` are long; if `git clone` reports "Filename too long", clone with `git clone -c core.longpaths=true https://github.com/FRACerqueira/adrpy-ai.git`.

For development (running the test suite), see [Contributing](#contributing).

## Quick Start

```bash
# Initialize a new ADR repository in the current structure
adrpy init --path .

# Create a new decision, status Proposed
adrpy new --path . --title "Use PostgreSQL for the primary datastore" --domain data --scope backend

# Approve it -- status becomes Accepted
adrpy approve --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md

# List every decision in the repository
adrpy explore --path .
```

Every call above returns JSON on stdout. For example, `explore` after the steps above returns:

```json
{
  "success": true,
  "data": {
    "decisions": [
      {
        "filename": "ADR001V01-use-postgre-sql-for-the-primary-datastore.md",
        "scheme": "current",
        "number": 1,
        "version": 1,
        "title": "use-postgre-sql-for-the-primary-datastore",
        "header": {
          "is_valid": true,
          "scope": "backend",
          "domain": "data",
          "state": "valid",
          "status_create": "Proposed",
          "status_update": "Accepted"
        }
      }
    ],
    "consistency": {"errors": []},
    "warnings": []
  }
}
```

(Trimmed for readability — the real response includes a few more fields per decision.)

Only files with an **ADR name** are decisions: the configured `prefix` (`ADR` by default, any case), the number, a mandatory `V` version, an optional `R` revision, then the separator and the title — `ADR001V01-use-postgre-sql.md` — plus a `--NNN` suffix on a successor. Any other `.md` in the decisions folder (a README, `0001-use-postgres.md`, `2024-01-15-meeting.md`) is ignored, unless `migrationpattern` describes it as a legacy name; `check` and `explore` warn about one whose name starts with a digit. A legacy name is a decision only while the repository is not adopted yet or when it has a header: once any file has a valid header `migrate` did not write (created by the tool or AdrPlus, or copied by hand — from then on `migrate` no longer runs), a legacy name without a header is not a decision — every command ignores it, and `check`, `explore` and every lifecycle command name it in `warnings`. Headers `migrate` wrote do not end the adoption: after a partial run, the files left keep blocking until `migrate` finishes them. The exact rule is under "ADR names" in [`doc/lifecycle.md`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/lifecycle.md).

## Commands

| Command | Purpose |
|---|---|
| [`init`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/init.md) | Initializes an ADR repository: writes `adr-config.adrplus` and creates the decisions folder. |
| [`new`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/new.md) | Creates a new decision, status `Proposed`. |
| [`approve`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/approve.md) | Marks a `Proposed` decision `Accepted`. |
| [`reject`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/reject.md) | Marks a `Proposed` decision `Rejected`. |
| [`undo`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/undo.md) | Reverts a decision's `Accepted`/`Rejected` status back to `Proposed`. |
| [`supersede`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/supersede.md) | Marks an `Accepted` decision `Superseded` and creates its successor. |
| [`version`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/version.md) | Creates a new major version of an `Accepted`/`Rejected` decision. |
| [`revise`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/revise.md) | Creates a new revision (wording fix) of an `Accepted`/`Rejected` decision. |
| [`migrate`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/migrate.md) | Adds an adrpy-compliant header to existing, hand-written decision files. |
| [`explore`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/explore.md) | Lists every decision file in the repository, on a best-effort basis. |
| [`check`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/check.md) | Validates every decision in the repository and lists every inconsistency found. |
| [`config`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/config.md) | Reads or updates an existing repository's own `adr-config.adrplus`. |
| [`installconfig`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/installconfig.md) | Reads or updates the per-user, install-level default config (seeds new repositories, supplies a `migrate` fallback). |
| [`log`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/log.md) | Writes a decision-log entry -- the lighter-weight sibling of a formal ADR. It refuses while the log folder holds a file that is not an entry, which `check` and `explore` warn about. |
| [`help`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/help.md) | Lists every command, or describes one of them in full. |

Bare `adrpy help` (or running `adrpy` with no arguments at all) lists every command's name and a one-line summary only, plus a curated preview of the config values a fresh `init` on this machine would actually produce (`defaults`, sourced from this machine's own `installconfig` when one is set up, or the built-in default otherwise — not every field; `template`, `migrationpattern`, `headerdisclaimer`, `folderlog`, the 11 header-row labels, and the plugin fields are all left out of this quick-glance preview on purpose, `adrpy installconfig`/`adrpy config` return every field including those) -- kept short on purpose, since the full contract of all 15 commands at once is a lot to read. A specific command's full argument list, types, and every failure code it can return is available at any time via:

```bash
adrpy help <command>
```

`adrpy help --full` returns every command's full contract in one call, if that's genuinely what's needed. The same contract is also available as reference pages under [`doc/commands/`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/INDEX.md), one per command, generated from `describe()` (a test fails when a page drifts from it). Which status each command can move a decision to, and what stops it, is on one page: [`doc/lifecycle.md`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/lifecycle.md).

## Checking a repository (`adrpy check`)

```bash
adrpy check --path .
```

`check` validates the whole repository and writes nothing. It exits `0` with `{"success": true, "data": {"decisions": <count>, ...}}` when every rule holds, and `1` with `repository-inconsistent` otherwise; `data.errors` lists every broken rule, each with its `code`, `file`, `related_files`, `detail` (`null` when the code says it all) and a repair `hint`. The rules are listed in [`doc/lifecycle.md`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/lifecycle.md). Every lifecycle command runs the same validation first and refuses the same way, so a repository `check` accepts is one every command can act on.

As a git pre-commit hook (`.git/hooks/pre-commit`, made executable) — the JSON goes to `/dev/null`, the human-readable `detail` still reaches the terminal on stderr. `check` reads the working tree, not what is staged: to check what you commit, stash the unstaged changes and untracked files first (`git stash push --keep-index --include-untracked`, then `git stash pop` after the commit) or use a hook manager that does it for you:

```sh
#!/bin/sh
adrpy check --path . > /dev/null || {
  echo "adrpy check failed; run 'adrpy check --path .' to see every error and its hint." >&2
  exit 1
}
```

As a GitHub Actions workflow (`.github/workflows/adr-check.yml`):

```yaml
name: ADR check
on: [push, pull_request]
jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install adrpy-ai
      - run: adrpy check --path .
```

## One owner per working copy

adrpy has no concurrency control, by design:

- **Git coordinates people.** Each person or agent works on their own clone or branch; adrpy never calls git. A merge that breaks a rule — two branches that each created `ADR005`, say — is exactly what `adrpy check` reports, with the hint for the repair.
- **One adrpy command at a time on a working copy.** Don't run adrpy (or `adrpy-skills`) commands in parallel on the same working copy: nothing locks it, and the last command to write a file wins.
- **What is still guaranteed.** Every file write is atomic (a reader sees the old file or the new one, never a partial one), a new decision is never created over an existing file (`file-already-exists`), and temp files left behind by an interrupted write are cleaned up later.
- **Detects, does not prevent.** A repository left inconsistent — by a hand edit, a merge, parallel commands, or a multi-file write that stopped halfway — is refused by every lifecycle command until it is repaired, and reported by `adrpy check`.
## Using adrpy-ai with AI Coding Agents

adrpy-ai was designed for this from the start, not adapted to it afterward:

- Every response is a single, well-formed JSON object — safe to parse without scraping human-readable text.
- Failure codes are stable, documented strings (e.g. `repository-inconsistent`, `config-already-exists`), not free-text messages an agent has to pattern-match.
- Don't let two agents (or an agent and a person) run `adrpy` commands in parallel on the same working copy — see [One owner per working copy](#one-owner-per-working-copy).
- `adrpy help <command>` is the same machine-readable contract an agent can fetch at runtime, instead of relying on documentation baked into its own training data (which can drift out of date).
- No command ever blocks on a prompt. An agent driving `adrpy` through a shell tool never has to detect and answer an interactive question.

**Working with an AI agent.** To have an agent follow these rules without repeating them in every prompt, install the `adrpy` skill in the repository for your assistant: `adrpy-skills install --skill adrpy --provider claude` (or `cursor`, `copilot`, `agentsmd`; without `--provider` it writes files for every provider). It tells the agent to run `adrpy help` and `adrpy check --path .` before touching the decisions folder, to follow each error's `hint`, to change decision files only through the commands (never renaming, hand-writing or hand-editing them, and never removing a successor's `--NNN` suffix), and to run one command at a time. See [Installing the judgment layer](#installing-the-judgment-layer-adrpy-skills).

`adrpy` itself is deliberately mechanical: it manages the ADR/decision-log *record*, never the judgment (when a decision needs recording, when a hardening review is due, when to close a review cycle). That judgment layer ships separately, as `adrpy-skills` — see [ADR009V01](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/adr/ADR009V01-ai-coding-agent-skills-installer-ships-as-a-separate-adrpy-skills-entry-point-with-per-provider-full-body-or-stub-delivery.md) and [`doc/skills/`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/skills/README.md).

## Installing the judgment layer (`adrpy-skills`)

A separate console script, installed by the same `pip install adrpy-ai` — opt-in, and never called by `adrpy` itself. It installs three vendor-neutral skills for whichever AI coding assistants you use: `adrpy` (how an agent drives the CLI itself), `decision-log` and `pre-release-audit`:

```bash
adrpy-skills install --provider claude         # every bundled skill, for one assistant
adrpy-skills install --skill decision-log --provider claude,cursor
adrpy-skills install                           # every bundled skill, every supported provider
adrpy-skills list                             # what's installed where, and whether any of it has drifted
```

Supported providers: `claude` (Claude Code, project or global scope), `cursor`, `copilot` (GitHub Copilot), and `agentsmd` (a generic `AGENTS.md`, editing only its own marked block). Every file `adrpy-skills` writes carries a content-hash marker, so a plain re-run after `pip install --upgrade` picks up updates safely, while anything you hand-edited since is left alone unless you pass `--force`. Full command reference: [`doc/skills/`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/skills/README.md). How well an agent follows the skills depends on its model: they were tested with Claude Code, where a model at least as capable as Claude Sonnet 5 is recommended for any task that writes decisions; the other providers were not tested with a real agent (see "Which model to use" there).

## Configuration

A repository's own settings (ADR numbering, naming scheme, header labels, status labels) live in `adr-config.adrplus`, edited via `adrpy config`. For a new repository, `adrpy init` seeds those settings from, in order: an explicit `--seed <file>`, a per-user install-level default (`adrpy installconfig`, if one has been set up on this machine), or a built-in default. Status labels, the naming-scheme separator and the prefix can only be changed while doing so wouldn't break recognition of an already-written decision (see [ADR004](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/adr/ADR004V02-decision-status-recognition-uses-a-hidden-canonical-marker;-status-labels-and-the-filename-separator-both-gain-an-existing-decisions-guard.md)) — in practice this means the four status labels, the separator and the prefix become permanently fixed the moment the repository has its first decision of any kind, while the legacy-scheme `migrationpattern` becomes permanently fixed only once the repository has its first migrated legacy-scheme decision (one with a valid header; until then it can also be changed or cleared with `adrpy config --migrationpattern ""`); `adrpy help config` documents the exact failure codes.

`adrpy installconfig` manages that per-user default directly — the same schema as a repository's own config, so it doubles as a way to keep every new repository on a machine consistent without repeating flags every time. Both `init` and `installconfig` also accept `--language` (e.g. `pt-br`), which seeds the built-in header/status labels and default template from a bundled language pack instead of the English defaults; it's a bootstrapping-only convenience — an already-initialized repository's own `config` has no equivalent flag, since its labels are already concrete values on disk, not something to re-derive from a language choice.

## Relationship to AdrPlus

adrpy-ai started as a Python re-implementation of [AdrPlus](https://github.com/FRACerqueira/AdrPlus) (C#/.NET), by the same author, and is now the reference for the rules both tools share: AdrPlus follows adrpy, not the other way round. It is not a fork and shares no code with it. adrpy reads AdrPlus 1.0.0 repositories as they are — the same `adr-config.adrplus`, the same 12-line header, files AdrPlus migrated. On top of that shared format, adrpy validates the whole repository before acting, enforcing rules AdrPlus 1.0.0 does not (see [below](#adopting-adrpy-on-an-adrplus-100-repository)), and adds the `folderlog` config field ([ADR007](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/adr/ADR007V01-decision-log-directory-becomes-an-independent,-recursively-scanned-config-field-instead-of-a-fixed-sibling-of-folderadr--003.md)). It has no interactive wizard (everything is flag-driven) and no plugin system (AdrPlus's is not ported).

## Adopting adrpy on an AdrPlus 1.0.0 repository

No conversion step is needed: point adrpy at the repository and run

```bash
adrpy check --path .
```

AdrPlus 1.0.0 can leave a few states that adrpy's rules do not allow. Every lifecycle command refuses the repository while one of them is there, so repair them by hand once, commit, and adrpy keeps the repository consistent from then on. Each error in `data.errors` names the file, the related files and the repair in its `hint`:

| State AdrPlus 1.0.0 can leave | Reported as | Repair (by hand) |
|---|---|---|
| An older version still `Superseded` next to a newer version that is not `Rejected` | `superseded-not-live` | Move the Superseded cell to the live (latest) member, or set the newer member's Changed cell to `Rejected`. |
| Two `Superseded` members in one family | `superseded-duplicate` | Keep the Superseded cell on the live member and clear it on the others (their successors then need their suffix or status repaired too). |
| Two successors that are not `Rejected` naming the same predecessor | `multiple-live-successors` | Keep the one the predecessor's Superseded cell points at; set the others' Changed cell to `Rejected`, or remove them. |
| A `Superseded` cell pointing at a successor that was rejected | `superseded-without-successor` | Clear the Superseded cell, or fix its number. |
| A version or revision of a successor that was rejected, itself not `Rejected` | `rejected-successor-family-not-final` | Set its Changed cell to `Rejected`, or remove it. If the predecessor's Superseded cell still points at the rejected successor, clear it too (otherwise `superseded-without-successor`); the line then continues by superseding the predecessor again. |

A file with an ADR name but no header gets `no-header`; while no decision has a valid header that migrate did not write, `adrpy migrate` gives every such file a header in one run. `migrate` always needs a `migrationpattern`, set first with `adrpy config --migrationpattern ...` (config tolerates the `no-header` files for exactly this) or taken from the install-level config; it is needed even when every file already has an ADR name (the ADR name is read first). The pattern also makes a decision of every other name it matches — a dated note like `2024-01-15-meeting.md` — while the repository is not adopted yet (once a decision has a valid header `migrate` did not write, a matched name without one is ignored and warned about instead), so choose one that matches nothing else in the folder. Preview what a pattern reads with `adrpy explore --path . --migrationpattern <pattern>` (`migrationpattern_preview`, written nowhere), then set it with `adrpy config --migrationpattern` (which writes the config: `check` then fails with `no-header` on each matched file until `migrate` runs; `--migrationpattern ""` backs out). A re-run of `migrate` after a partial one migrates the files still without a header. The `migrationpattern` syntax (`N##:##T##[V##:##][R##:##][P##:##]`, with examples) is under "`migrationpattern` syntax" on the [`config` page](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/commands/config.md#migrationpattern-syntax). Once any decision has a valid header migrate did not write, `migrate` refuses (`already-tool-created-adrs-exist`): give the remaining files a header by hand. A `.md` whose name is not an ADR name (a README, an index) is ignored.

What an AdrPlus 1.0.0 header looks like — the 12 lines at the top of every decision, the status read from the label alone (adrpy also writes a hidden `<!-- Accepted -->` marker after the date; both forms are read):

```markdown
<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Use PostgreSQL|
|Version|01|
|Revision||
|Scope||
|Domain||
|Created|Proposed (2026-01-10)|
|Changed|Accepted (2026-01-12)|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
```

A file AdrPlus (or adrpy) migrated says so on line 2, `|Adr-Plus Fields|Values Migrated <!-- Migrated -->|`, and may have blank Version and status cells.

## Architecture and Design Decisions

This project records its own architectural decisions as it makes them:

- [`doc/architecture.md`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/architecture.md) — how the codebase is put together and why: module layout, request lifecycle, the single-owner model, configuration layering, and the decision lifecycle, with diagrams.
- [`doc/adr/`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/adr/) — formal Architecture Decision Records, written using adrpy-ai itself (this project dogfoods its own tool).
- [`doc/decision-log/`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/decision-log/INDEX.md) — a running log of audit findings, documentation corrections, and deferred/accepted trade-offs, generated from individual entries and never hand-edited.
- [`doc/decision-log-workflow.md`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/decision-log-workflow.md) — the step-by-step workflow (with a diagram) for deciding whether something belongs in an ADR or in the decision log, and how to write either one.
- [`doc/skills/`](https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/skills/README.md) — how `adrpy-skills` installs that same judgment layer for AI coding agents, and how it decides what to write, per provider.

If you're evaluating this project's engineering rigor rather than just its feature set, `doc/adr/` and `doc/decision-log/` are the primary evidence, not this README.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](https://github.com/FRACerqueira/adrpy-ai/blob/main/CONTRIBUTING.md) for development setup, the test/verification discipline this project expects of every change, and how to submit a pull request. Please also read the [Code of Conduct](https://github.com/FRACerqueira/adrpy-ai/blob/main/CODE_OF_CONDUCT.md).

Found a security issue? See [SECURITY.md](https://github.com/FRACerqueira/adrpy-ai/blob/main/SECURITY.md) instead of opening a public issue.

Released changes are tracked in [CHANGELOG.md](https://github.com/FRACerqueira/adrpy-ai/blob/main/CHANGELOG.md).

## License

[MIT](https://github.com/FRACerqueira/adrpy-ai/blob/main/LICENSE) — Copyright (c) 2026 Fernando Cerqueira.
