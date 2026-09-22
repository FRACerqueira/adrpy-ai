<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills install`

Installs one or more bundled skills for one or more AI-coding-agent providers.

## Description

Writes the requested (provider, skill) pairs to disk, wrapped in the shape each provider expects (full skill body for claude/cursor, a short stub pointing at one shared doc for copilot/agentsmd). Every write is protected by a content-hash marker: a file that already exists with no marker at all is reported as `foreign` and left untouched; a file whose marker no longer matches its own current content is reported as `drifted` and also left untouched -- in both cases only `--force` overwrites it. For agentsmd, a skill's own start/end block that's truncated (missing its closing tag) or duplicated (more than one complete block for the same skill) is reported as `malformed` and given the same treatment as `foreign`. For copilot/agentsmd, the one shared doc a skill's stub points at is written (and reported in `installed` under provider `shared-doc`) before that provider's own file, never after -- if the shared doc itself is `foreign`/`drifted` and blocked (without `--force`), every stub-mode provider that would reference it is also skipped, reported with reason `shared-doc-blocked`, rather than writing a stub that points at content never actually verified or regenerated. `--target global` combined with any provider other than `claude` fails with `usage-error` (cursor/copilot/agentsmd have no global-scope concept). Never runs unless explicitly invoked -- `adrpy-skills` is a separate entry point from `adrpy` and is never called by it.

## Arguments

### `--provider` / `-p` *(optional, string)*

Comma-separated list of providers to install for: `claude`, `cursor`, `copilot`, `agentsmd`. Defaults to `all` (every bundled provider) when omitted.

### `--skill` / `-s` *(optional, string)*

Comma-separated list of skills to install: `comment-audit`, `decision-log`, `pre-release-audit`. Defaults to `all` (every bundled skill) when omitted.

### `--target` / `-t` *(optional, string)*

`project` (default) writes under `--path`; `global` writes under your own home directory (only meaningful for `claude` -- every other provider fails with `usage-error` under `--target global`).

### `--path` *(optional, string)*

Repository root to install into. Defaults to `.`. Only meaningful for `--target project`.

### `--force` / `-f` *(optional, switch)*

Overwrites a `foreign` or `drifted` file/block instead of skipping it. Presence-only: pass just `--force`, not `--force true/false`.

## Failure codes

| Code | Condition |
|---|---|
| `usage-error` | An unknown `--provider`, `--skill`, or `--target` value was given (`--target` accepts only `project`/`global`), or `--target global` was combined with a provider that has no global-scope concept (anything but `claude`). |
| `io-error` | A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |

## Example

```bash
adrpy-skills install --skill decision-log,pre-release-audit --provider claude,cursor
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy-skills help install` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
