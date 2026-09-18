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
- [Configuration](#configuration)
- [Relationship to AdrPlus](#relationship-to-adrplus)
- [Architecture and Design Decisions](#architecture-and-design-decisions)
- [Contributing](#contributing)
- [License](#license)

## Why adrpy-ai

- **No wizard, ever.** Every command is fully driven by flags. Nothing waits for a keypress, so it's safe to script and safe for an agent to call without a human in the loop.
- **JSON in, JSON out.** Every response is a single JSON object on stdout (`{"success": true/false, "data"/"code": ...}`), with a fixed, documented set of failure codes per command — no output your own tooling has to guess the shape of.
- **Self-documenting.** `adrpy help <command>` returns the exact same structured contract (arguments, types, failure codes) this README describes — the documentation and the code can't silently drift apart, because they're the same artifact.
- **Zero runtime dependencies.** `pip install adrpy-ai` (or install from source) pulls in nothing else.
- **A full lifecycle, not just file creation.** `init`, `new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`, `migrate`, `config`, `installconfig` — the whole decision lifecycle, not a one-shot generator.
- **Concurrency-safe by design.** A repository-wide lock covers every command that reads-then-writes shared repository state, with an explicit, documented failure boundary instead of an unstated hope that two callers never collide. See [ADR001](doc/adr/ADR001V01-repository-lock-covers-the-full-critical-section-of-every-mutating-command.md).

## Installation

adrpy-ai isn't published to PyPI yet. Install from source:

```bash
git clone https://github.com/FRACerqueira/adrpy-ai.git
cd adrpy-ai
pip install .
adrpy help
```

Requires Python 3.11+.

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
| `init` | Initializes an ADR repository: writes `adr-config.adrplus` and creates the decisions folder. |
| `new` | Creates a new decision, status `Proposed`. |
| `approve` | Marks a `Proposed` decision `Accepted`. |
| `reject` | Marks a `Proposed` decision `Rejected`. |
| `undo` | Reverts a decision's `Accepted`/`Rejected` status back to `Proposed`. |
| `supersede` | Marks an `Accepted` decision `Superseded` and creates its successor. |
| `version` | Creates a new major version of an `Accepted`/`Rejected` decision. |
| `revise` | Creates a new revision (wording fix) of an `Accepted`/`Rejected` decision. |
| `migrate` | Adds an adrpy-compliant header to existing, hand-written decision files. |
| `explore` | Lists every decision file in the repository, on a best-effort basis. |
| `config` | Reads or updates an existing repository's own `adr-config.adrplus`. |
| `installconfig` | Reads or updates the per-user, install-level default config (seeds new repositories, supplies a `migrate` fallback). |
| `help` | Lists every command, or describes one of them in full. |

Every command's full argument list, types, and every failure code it can return is available at any time via:

```bash
adrpy help <command>
```

## Using adrpy-ai with AI Coding Agents

adrpy-ai was designed for this from the start, not adapted to it afterward:

- Every response is a single, well-formed JSON object — safe to parse without scraping human-readable text.
- Failure codes are stable, documented strings (e.g. `repository-locked`, `config-already-exists`), not free-text messages an agent has to pattern-match.
- `adrpy help <command>` is the same machine-readable contract an agent can fetch at runtime, instead of relying on documentation baked into its own training data (which can drift out of date).
- No command ever blocks on a prompt. An agent driving `adrpy` through a shell tool never has to detect and answer an interactive question.

## Configuration

A repository's own settings (ADR numbering, naming scheme, header labels, status labels) live in `adr-config.adrplus`, edited via `adrpy config`. For a new repository, `adrpy init` seeds those settings from, in order: an explicit `--seed <file>`, a per-user install-level default (`adrpy installconfig`, if one has been set up on this machine), or a built-in default.

`adrpy installconfig` manages that per-user default directly — the same schema as a repository's own config, so it doubles as a way to keep every new repository on a machine consistent without repeating flags every time.

## Relationship to AdrPlus

adrpy-ai is a Python re-implementation of [AdrPlus](https://github.com/FRACerqueira/AdrPlus) (C#/.NET), by the same author. It is not a fork and does not share a codebase with it — command behavior was verified directly against the reference tool's own source where fidelity mattered, and every deliberate difference (a missing feature, a changed default, a divergent error shape) is recorded in this repository's own [decision log](doc/decision-log/INDEX.md), not left undocumented. Two concrete, intentional differences worth knowing up front: adrpy-ai has no interactive wizard (everything is flag-driven), and AdrPlus's plugin system is not ported (out of scope for this project; see the decision log for why).

## Architecture and Design Decisions

This project records its own architectural decisions as it makes them:

- [`doc/adr/`](doc/adr/) — formal Architecture Decision Records, written using adrpy-ai itself (this project dogfoods its own tool).
- [`doc/decision-log/`](doc/decision-log/INDEX.md) — a running log of audit findings, confirmed divergences from the reference tool, and deferred/accepted trade-offs, generated from individual entries and never hand-edited.

If you're evaluating this project's engineering rigor rather than just its feature set, those two folders are the primary evidence, not this README.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, the test/verification discipline this project expects of every change, and how to submit a pull request. Please also read the [Code of Conduct](CODE_OF_CONDUCT.md).

Found a security issue? See [SECURITY.md](SECURITY.md) instead of opening a public issue.

## License

[MIT](LICENSE) — Copyright (c) 2026 Fernando Cerqueira.
