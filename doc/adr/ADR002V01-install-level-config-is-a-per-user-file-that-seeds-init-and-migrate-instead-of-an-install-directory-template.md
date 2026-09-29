<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Install-level config is a per-user file that seeds init and migrate instead of an install-directory template|
|Version|01|
|Revision||
|Scope|install-config|
|Domain|configuration|
|Created|Proposed (2026-09-18) <!-- Proposed -->|
|Changed|Accepted (2026-09-18) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Install-level config is a per-user file that seeds init and migrate instead of an install-directory template

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided directly after a library/architecture evaluation and a corrected scoping pass over the full repo-config schema.

Technical Story: reopens `2026-09-15--deferred--migrate--no-install-level-fallback-for-migrationpattern.md`'s own named reopening condition ("an install-level/app-config module exists in adrpy-ai").

## Context and Problem Statement

adrpy-ai has never had an install-level/app-config module: `init` without `--seed` always builds from a single bundled `default_repo_config.json`, and `migrate` fails immediately with `migration-pattern-not-configured` whenever a repository's own `migrationpattern` is empty. An install-level layer would give both commands a per-installation source instead: a full repo-config-shaped template consumed both by `init` (as its default seed) and by `migrate` (as a `migrationpattern` fallback that is also persisted back into the repository's own config once found). The module's initial scoping considered only `migrationpattern`, based on the deferred entry's own narrow research scope; the real missing surface is the whole schema — `lenseq`, `lenversion`, `lenrevision`, `casetransform`, `separator`, `prefix`, and every header/status label — none of which are configurable at install level today either. adrpy-ai's own pip packaging also rules out install-directory-relative storage: writing into a package's own install/site-packages directory is unsafe (permissions, wiped on reinstall, often shared). What should this module's file location, schema, command surface, and consumption points be?

## Decision Drivers

* `lenseq`, case-format, `lenversion`/`lenrevision` are equally unconfigurable at install level today, not just `migrationpattern` — the gap is the full schema, not a single field.
* `pyproject.toml`'s own project description states "no wizard, JSON-only output" — a foundational, project-wide premise, not a per-command choice. No interactive console assistant, matching `config.py`'s own existing one-flag-per-field pattern.
* `dependencies = []` is an explicit, load-bearing project constraint (`pyproject.toml`) — ruling out a dependency such as `platformdirs` in favor of a small hand-rolled per-OS path resolver.
* Writing into a pip package's own install directory is unsafe (permissions, wiped on reinstall, often shared by unrelated users) — ruling out install-directory-relative storage.

## Considered Options

* Per-user file (OS-appropriate config directory), full repo-config schema, new `installconfig` command.
* Install-directory-relative file.
* Extend the existing `config` command with an `--install` scope instead of adding a new command.

## Decision Outcome

Chosen option: "Per-user file, full repo-config schema, new `installconfig` command", because it covers the real, full-schema gap the deferred entry only partially named, fits the project's existing no-wizard and zero-dependency constraints, and reuses a pattern (`--seed <file>`) the project already has and already tests instead of inventing new mechanism.

The decision has three parts:

1. **File and schema.** A single per-user file (e.g. `%APPDATA%\adrpy\install-config.json` on Windows, `~/.config/adrpy/install-config.json` on Linux/macOS — resolved by a small hand-rolled per-OS helper, no new dependency), holding the *full*, seed-valid repo-config shape — every field `init --seed` accepts, including `activeplugins`. `activeplugins` is carried at its own fixed default value (matching `default_repo_config.json`'s own value), never exposed as an `installconfig` flag, following `config`'s own existing precedent (its help text: "`activeplugins` is never included in that read result or accepted as a field to update... do not round-trip it as `init --seed` input without adding `activeplugins` back") — `installconfig` is responsible for keeping the field present in the file it writes, so `init` can consume it directly with no manual repair step. The file is not kept next to the install directory, because a pip package's own install/site-packages directory is not a safe place to write (see Decision Drivers). The file may not exist at all — that is the normal state for a fresh installation, not an error condition.
2. **Command surface.** A new `installconfig` command, kept separate from the existing repository-scoped `config` command rather than extending it with a scope flag — the same one-command-per-concern shape the project already uses, with one flag per schema field (following `config.py`'s own `_EDITABLE_FIELDS` pattern, including the same inherited constraint that `migrationpattern`/`template`/`prefix` cannot be set to an empty string by flag — only `--seed` can) plus a `--seed <file>` bulk-import flag, matching `init --seed`. `installconfig` writes only per-user state (this file), never the repository (`.adrpy.json` / the `folderadr` folder). A bare `installconfig` (no flags) reads the current values back, same shape as `config`'s own bare-read form; if the file does not exist, the result states that explicitly (not-configured) rather than silently reporting built-in defaults as if they had been chosen — exact JSON shape left to implementation, but the distinction itself is decided here since a JSON-only, agent-driven contract needs it to be unambiguous.
3. **Consumption points.**
   * `init` with no `--seed`: uses the install-level file as its seed if the file exists; otherwise falls back to today's bundled `default_repo_config.json`, with no error and no nag — this is the expected state for any installation that has never configured one. `--language` cannot be combined with a bare `init` when the install-level file exists, for the same reason `--language` already cannot be combined with an explicit `--seed` today (both are full content sources; the caller must pick one explicitly rather than have one silently win) — this extends an existing precedence rule to the new implicit-seed case instead of leaving it to be decided silently during implementation.
   * `migrate`: unchanged fallback trigger (only consulted when the repository's own `migrationpattern` is empty), but when the install-level file supplies a non-empty value, that value is also persisted back into the repository's own `.adrpy.json`, so the repository does not depend on one machine's install-level file for as long as its migrated decisions keep their legacy names (ADR012V01) — a new write reason on an existing command, written with the same atomic per-file write as every other write (ADR001). If `migrationpattern` is empty in *both* places, `migrate` keeps adrpy-ai's clear `migration-pattern-not-configured` error rather than proceeding and failing later — a deliberate, stated choice, consistent with this project's "AI-agent-driven use" positioning (predictable, structured failures over silent best-effort).

**Round 43 note (2026-09-24), owner decision.** The repository-scoped `config` command now accepts `--migrationpattern ""` to clear the pattern, under the same guard as any other `migrationpattern` change (refused while a recognized legacy-scheme decision would lose recognition). `template` and `prefix` still cannot be set to an empty string by flag, and `installconfig` is unchanged.

### Positive Consequences

* Closes the real gap: the full schema is now configurable at install level, not only `migrationpattern`.
* Reuses an existing, already-tested pattern (`--seed`) for bulk setup, instead of adding a second mechanism.
* Preserves the project's existing clear-failure semantics (`migration-pattern-not-configured`) instead of proceeding and failing later.

### Negative Consequences

* A new module and command to build and maintain (`installconfig.py`, a per-OS path resolver, `migrate`'s write-back logic).
* `migrate` gains a new, non-obvious write reason (persisting the install-level fallback value back into the repository's own config) — worth flagging explicitly in `migrate`'s own `describe()` text when implemented, so a caller reading the command's own contract sees it rather than discovering it by surprise.

## Pros and Cons of the Options

### Per-user file, full schema, new `installconfig` command

* Good, because it is safe under Python packaging norms (no writes into the package's own install directory).
* Good, because it covers the real, full-schema gap rather than the narrower `migrationpattern`-only scope first considered.
* Good, because it reuses the existing `--seed` pattern instead of adding new mechanism.
* Bad, because it needs a hand-rolled per-OS path resolver the project has to build and maintain.

### Install-directory-relative file

* Bad, because writing into a pip package's own install/site-packages directory is unsafe — permissions, wiped on reinstall, often shared across users on the same machine.

### Extend `config` with an `--install` scope instead of a new command

* Bad, because it changes the signature and behavior of an existing, already-shipped command for a scope it does not support today, rather than adding an isolated new one — more invasive than the gain justifies at this project's real scale.

## Links

* Satisfies the reopening condition of `doc/decision-log/2026-09-15--deferred--migrate--no-install-level-fallback-for-migrationpattern.md` ("an install-level/app-config module exists in adrpy-ai") once this decision is implemented — not yet, as of this ADR being accepted; the module exists only as a decision until then.
* `doc/adr/ADR001V01-single-owner-working-copy-without-concurrency-control,-validating-the-whole-repository-before-every-lifecycle-action.md` — `migrate`'s write-back uses the same atomic per-file write as every other write; adrpy has no concurrency control (one owner per working copy).
