# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project intends to follow [Semantic Versioning](https://semver.org/) once it reaches `1.0.0`.

## [Unreleased]

### Added

- Full ADR lifecycle: `init`, `new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`.
- `migrate` — adds an adrpy-compliant header to existing, hand-written decision files.
- `explore` — best-effort listing of every decision file in a repository.
- `config` — reads or updates an existing repository's own `adr-config.adrplus`.
- `installconfig` — per-user, install-level default configuration, seeding new repositories and supplying a `migrate` fallback for `migrationpattern`.
- `log` — writes a decision-log entry, the lighter-weight sibling of a formal ADR (see [ADR003](doc/adr/ADR003V01-decision-log-entries-separate-human-reviewed-judgment-from-tool-executed-mechanics-via-a-future-adrpy-log-command.md)).
- `supersede --title` — optionally gives a successor its own title instead of always carrying the predecessor's own forward.
- `folderlog` — the decision-log directory is now an independently configurable, recursively-scanned `adr-config.adrplus` field, decoupled from `folderadr` (see [ADR007](doc/adr/ADR007V01-decision-log-directory-becomes-an-independent,-recursively-scanned-config-field-instead-of-a-fixed-sibling-of-folderadr.md)).
- A single, central `FailureCodes` registry for every failure code this tool can return, replacing scattered string literals (see [ADR005](doc/adr/ADR005V01-failure-codes-and-shared-constants-gain-dedicated,-closed-registry-classes.md)).
- A structured `failure_codes` field on every command's `describe()` response, listing every failure code that command can actually return with a one-line condition each — the same information `doc/commands/*.md`'s own new "Failure codes" table shows, now also machine-readable in the live JSON contract (see [ADR008](doc/adr/ADR008V01-describe()-gains-a-structured-failure-codes-field,-sourced-from-shared-per-module-dictionaries-for-universally-reachable-codes.md)).
- A repository-wide lock covering the full critical section of every mutating command, with a documented failure boundary (see [ADR001](doc/adr/ADR001V01-repository-lock-covers-the-full-critical-section-of-every-mutating-command.md)).
- Public project scaffolding: `LICENSE` (MIT), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, this changelog.

### Security

- Closed 3 confirmed bypasses of the `folderadr`/`folderlog` containment guard's schema-time string comparison: a `../` traversal, a backslash-separated nesting on Windows, and a bare case difference, each resolving to the same or a nested real directory despite comparing unequal as raw strings — the comparison now normalizes to the host's own path components (`.`/`..` collapsed, case-folded) before comparing.
- Closed a real-filesystem junction/symlink aliasing bypass of the `folderadr`/`folderlog` containment guard: the schema-time check alone cannot see a junction or symlink planted inside the repository tree that makes two configured paths alias the identical real directory — `reject_aliased_repo_folders` now additionally resolves both fields for real and compares the resolved paths, wired into `init`, `config`, and `log`.
- Narrowed a check-then-use TOCTOU window in that same real-filesystem guard: each of its 3 call sites now re-verifies immediately before committing its write, not just before starting, closing the gap between the check passing and the write landing.

[Unreleased]: https://github.com/FRACerqueira/adrpy-ai/commits/main
