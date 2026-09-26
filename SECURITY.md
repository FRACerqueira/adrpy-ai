# Security Policy

## Supported Versions

adrpy-ai is pre-1.0 (currently `0.1.0`). Only the latest released version is supported with security fixes until a stable `1.x` line exists.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

1. Go to the **Security** tab of this repository on GitHub.
2. Click **"Report a vulnerability"** (GitHub Private Vulnerability Reporting).
3. Include: affected version, reproduction steps, impact, and any suggested mitigation.

If private vulnerability reporting is unavailable for any reason, open an issue asking the maintainer, [@FRACerqueira](https://github.com/FRACerqueira), for a private channel — without any detail of the vulnerability in it.

This is a small, early-stage project maintained by one person — there's no formal SLA, but reports will be acknowledged and investigated as promptly as possible.

## Scope

adrpy-ai is a **local CLI tool** with zero runtime dependencies. It reads and writes files (Markdown decision files, JSON configuration) on the machine it runs on; it does not expose network services, does not handle credentials, and does not process untrusted remote input by design.

Concerns that are in scope:

- Path traversal or arbitrary file writes via command arguments or a malicious `adr-config.adrplus`/install-level config (this project's own repository boundary checks, e.g. `resolve_within`/`is_within` in `src/adrpy/core/security.py`, exist specifically to prevent this — a way around them is a real finding).
- Data corruption by a single invocation: a partially written file, a new decision created over an existing file, or a command acting on a repository that breaks a consistency rule instead of refusing it. Lost updates between commands run in parallel on the same working copy are not in scope: adrpy has no concurrency control by design — one owner per git working copy, git coordinates people (see [One owner per working copy](README.md#one-owner-per-working-copy)).
- Supply-chain issues — there are currently zero runtime dependencies, so this mainly concerns the build/dev toolchain itself (`hatchling`, `pytest`).

## Security Best Practices for Users

- Keep your Python installation and adrpy-ai up to date.
- Treat `adr-config.adrplus` and any install-level config file (`installconfig`) the same as any other file that controls what a tool writes to your filesystem — review it before trusting a config file you didn't author yourself (e.g. one shared by a teammate or copied from another machine).
