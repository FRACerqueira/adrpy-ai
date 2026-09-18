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
- A repository-wide lock covering the full critical section of every mutating command, with a documented failure boundary (see [ADR001](doc/adr/ADR001V01-repository-lock-covers-the-full-critical-section-of-every-mutating-command.md)).
- Public project scaffolding: `LICENSE` (MIT), `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, `SECURITY.md`, this changelog.

[Unreleased]: https://github.com/FRACerqueira/adrpy-ai/commits/main
