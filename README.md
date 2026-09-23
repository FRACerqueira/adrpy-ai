<img src="src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

# adrpy-ai

[![CI](https://github.com/FRACerqueira/adrpy-ai/actions/workflows/ci.yml/badge.svg)](https://github.com/FRACerqueira/adrpy-ai/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

**ADR lifecycle CLI for humans and AI agents alike — JSON-only, no wizard, zero dependencies.**

adrpy-ai manages [Architecture Decision Records](https://adr.github.io/) (ADRs) from the command line: create, approve, reject, undo, supersede, version, and revise decisions, plus migrate legacy hand-written files into the tool's own format. Every command takes flags in and returns JSON out — no interactive prompts, ever — so it works identically whether you're typing it yourself or an AI coding agent is driving it through a shell tool.

A Python companion to a reference tool, [AdrPlus](https://github.com/FRACerqueira/AdrPlus) (C#/.NET), also by Fernando Cerqueira. See [Relationship to AdrPlus](#relationship-to-adrplus) below.

## Table of Contents

- [Why adrpy-ai](#why-adrpy-ai)
- [Installation](#installation)
- [Quick Start](#quick-start)
- [Commands](#commands)
- [Using adrpy-ai with AI Coding Agents](#using-adrpy-ai-with-ai-coding-agents)
- [Installing the judgment layer (`adrpy-skills`)](#installing-the-judgment-layer-adrpy-skills)
- [Configuration](#configuration)
- [Relationship to AdrPlus](#relationship-to-adrplus)
- [Architecture and Design Decisions](#architecture-and-design-decisions)
- [Contributing](#contributing)
- [License](#license)

## Why adrpy-ai

- **No wizard, ever.** Every command is fully driven by flags. Nothing waits for a keypress, so it's safe to script and safe for an agent to call without a human in the loop.
- **JSON in, JSON out.** Every response is a single JSON object on stdout (`{"success": true/false, "data"/"code": ...}`), with a fixed, documented set of failure codes per command — no output your own tooling has to guess the shape of. A failure also carries `detail`, a human-readable explanation to show a person; decide on `code`/`data`, not on `detail`'s wording. The same text is copied to stderr for terminal use, outside the contract.
- **Self-documenting.** `adrpy help <command>` returns the exact same structured contract (arguments, types, failure codes) this README describes — the documentation and the code can't silently drift apart, because they're the same artifact.
- **Zero runtime dependencies.** `pip install adrpy-ai` (or install from source) pulls in nothing else.
- **A full lifecycle, not just file creation.** `init`, `new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`, `migrate`, `config`, `installconfig` — the whole decision lifecycle, not a one-shot generator.
- **Concurrency-safe by design.** A repository-wide lock covers every command that reads-then-writes shared repository state, with an explicit, documented failure boundary instead of an unstated hope that two callers never collide. See [ADR001](doc/adr/ADR001V01-repository-lock-covers-the-full-critical-section-of-every-mutating-command.md).

## Installation

```bash
pip install adrpy-ai
adrpy help
```

Requires Python 3.11+.

To install from source instead — for development, or to run a specific commit:

```bash
git clone https://github.com/FRACerqueira/adrpy-ai.git
cd adrpy-ai
pip install .
adrpy help
```

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
          "status_create": "Proposed",
          "status_update": "Accepted"
        }
      }
    ],
    "warnings": []
  }
}
```

(Trimmed for readability — the real response includes a few more fields per decision, all documented via `adrpy help explore`.)

## Commands

| Command | Purpose |
|---|---|
| [`init`](doc/commands/init.md) | Initializes an ADR repository: writes `adr-config.adrplus` and creates the decisions folder. |
| [`new`](doc/commands/new.md) | Creates a new decision, status `Proposed`. |
| [`approve`](doc/commands/approve.md) | Marks a `Proposed` decision `Accepted`. |
| [`reject`](doc/commands/reject.md) | Marks a `Proposed` decision `Rejected`. |
| [`undo`](doc/commands/undo.md) | Reverts a decision's `Accepted`/`Rejected` status back to `Proposed`. |
| [`supersede`](doc/commands/supersede.md) | Marks an `Accepted` decision `Superseded` and creates its successor. |
| [`version`](doc/commands/version.md) | Creates a new major version of an `Accepted`/`Rejected` decision. |
| [`revise`](doc/commands/revise.md) | Creates a new revision (wording fix) of an `Accepted`/`Rejected` decision. |
| [`migrate`](doc/commands/migrate.md) | Adds an adrpy-compliant header to existing, hand-written decision files. |
| [`explore`](doc/commands/explore.md) | Lists every decision file in the repository, on a best-effort basis. |
| [`config`](doc/commands/config.md) | Reads or updates an existing repository's own `adr-config.adrplus`. |
| [`installconfig`](doc/commands/installconfig.md) | Reads or updates the per-user, install-level default config (seeds new repositories, supplies a `migrate` fallback). |
| [`log`](doc/commands/log.md) | Writes a decision-log entry -- the lighter-weight sibling of a formal ADR. |
| [`help`](doc/commands/help.md) | Lists every command, or describes one of them in full. |

Bare `adrpy help` (or running `adrpy` with no arguments at all) lists every command's name and a one-line summary only, plus a curated preview of the config values a fresh `init` on this machine would actually produce (`defaults`, sourced from this machine's own `installconfig` when one is set up, or the built-in default otherwise — not every field; `template`, `migrationpattern`, `headerdisclaimer`, the 11 header-row labels, and the plugin fields are all left out of this quick-glance preview on purpose, `adrpy installconfig`/`adrpy config` return every field including those) -- kept short on purpose, since the full contract of all 14 commands at once is a lot to read. A specific command's full argument list, types, and every failure code it can return is available at any time via:

```bash
adrpy help <command>
```

`adrpy help --full` returns every command's full contract in one call, if that's genuinely what's needed. All three shapes are also available as prose reference pages under [`doc/commands/`](doc/commands/INDEX.md), one per command, generated directly from the same `describe()` contract.

## Using adrpy-ai with AI Coding Agents

adrpy-ai was designed for this from the start, not adapted to it afterward:

- Every response is a single, well-formed JSON object — safe to parse without scraping human-readable text.
- Failure codes are stable, documented strings (e.g. `repository-locked`, `config-already-exists`), not free-text messages an agent has to pattern-match.
- `adrpy help <command>` is the same machine-readable contract an agent can fetch at runtime, instead of relying on documentation baked into its own training data (which can drift out of date).
- No command ever blocks on a prompt. An agent driving `adrpy` through a shell tool never has to detect and answer an interactive question.

`adrpy` itself is deliberately mechanical: it manages the ADR/decision-log *record*, never the judgment (when a decision needs recording, when a hardening review is due, when to close a review cycle). That judgment layer ships separately, as `adrpy-skills` — see [ADR009V01](doc/adr/ADR009V01-ai-coding-agent-skills-installer-ships-as-a-separate-adrpy-skills-entry-point-with-per-provider-full-body-or-stub-delivery.md) and [`doc/skills/`](doc/skills/README.md).

## Installing the judgment layer (`adrpy-skills`)

A separate console script, installed by the same `pip install adrpy-ai` — opt-in, and never called by `adrpy` itself. It installs three vendor-neutral skills (`decision-log`, `pre-release-audit`, `comment-audit`) for whichever AI coding assistants you use:

```bash
adrpy-skills install                          # every bundled skill, every supported provider
adrpy-skills install --skill decision-log --provider claude,cursor
adrpy-skills list                             # what's installed where, and whether any of it has drifted
```

Supported providers: `claude` (Claude Code, project or global scope), `cursor`, `copilot` (GitHub Copilot), and `agentsmd` (a generic `AGENTS.md`, editing only its own marked block). Every file `adrpy-skills` writes carries a content-hash marker, so a plain re-run after `pip install --upgrade` picks up updates safely, while anything you hand-edited since is left alone unless you pass `--force`. Full command reference: [`doc/skills/`](doc/skills/README.md).

## Configuration

A repository's own settings (ADR numbering, naming scheme, header labels, status labels) live in `adr-config.adrplus`, edited via `adrpy config`. For a new repository, `adrpy init` seeds those settings from, in order: an explicit `--seed <file>`, a per-user install-level default (`adrpy installconfig`, if one has been set up on this machine), or a built-in default. Status labels and the naming-scheme separator can only be changed while doing so wouldn't break recognition of an already-written decision (see [ADR004](doc/adr/ADR004V02-decision-status-recognition-uses-a-hidden-canonical-marker;-status-labels-and-the-filename-separator-both-gain-an-existing-decisions-guard.md)) — in practice this means the four status labels and the separator become permanently fixed the moment the repository has its first decision of any kind, while the legacy-scheme `migrationpattern` becomes permanently fixed only once the repository has its first legacy-scheme decision specifically; `adrpy help config` documents the exact failure codes.

`adrpy installconfig` manages that per-user default directly — the same schema as a repository's own config, so it doubles as a way to keep every new repository on a machine consistent without repeating flags every time. Both `init` and `installconfig` also accept `--language` (e.g. `pt-br`), which seeds the built-in header/status labels and default template from a bundled language pack instead of the English defaults; it's a bootstrapping-only convenience — an already-initialized repository's own `config` has no equivalent flag, since its labels are already concrete values on disk, not something to re-derive from a language choice.

## Relationship to AdrPlus

adrpy-ai is a Python re-implementation of [AdrPlus](https://github.com/FRACerqueira/AdrPlus) (C#/.NET), by the same author. It is not a fork and does not share a codebase with it — command behavior was verified directly against the reference tool's own source where fidelity mattered, and every deliberate difference (a missing feature, a changed default, a divergent error shape) is recorded in this repository's own [decision log](doc/decision-log/INDEX.md), not left undocumented. Two concrete, intentional differences worth knowing up front: adrpy-ai has no interactive wizard (everything is flag-driven), and AdrPlus's plugin system is not ported (out of scope for this project; see the decision log for why).

## Architecture and Design Decisions

This project records its own architectural decisions as it makes them:

- [`doc/architecture.md`](doc/architecture.md) — how the codebase is put together and why: module layout, request lifecycle, the concurrency model, configuration layering, and the decision lifecycle, with diagrams.
- [`doc/adr/`](doc/adr/) — formal Architecture Decision Records, written using adrpy-ai itself (this project dogfoods its own tool).
- [`doc/decision-log/`](doc/decision-log/INDEX.md) — a running log of audit findings, confirmed divergences from the reference tool, and deferred/accepted trade-offs, generated from individual entries and never hand-edited.
- [`doc/decision-log-workflow.md`](doc/decision-log-workflow.md) — the step-by-step workflow (with a diagram) for deciding whether something belongs in an ADR or in the decision log, and how to write either one.
- [`doc/skills/`](doc/skills/README.md) — how `adrpy-skills` installs that same judgment layer for AI coding agents, and how it decides what to write, per provider.

If you're evaluating this project's engineering rigor rather than just its feature set, `doc/adr/` and `doc/decision-log/` are the primary evidence, not this README.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the test/verification discipline this project expects of every change, and how to submit a pull request. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md).

Found a security issue? See [SECURITY.md](SECURITY.md) instead of opening a public issue.

Released changes are tracked in [CHANGELOG.md](CHANGELOG.md).

## License

[MIT](LICENSE) — Copyright (c) 2026 Fernando Cerqueira.
