<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills install`

Installs one or more bundled skills for one or more AI-coding-agent providers.

## Description

Writes the requested (provider, skill) pairs to disk, wrapped in the shape each provider expects (full skill body for claude/cursor, a short stub pointing at one shared doc for copilot/agentsmd). Every write is protected by a content-hash marker: a file that already exists with no marker at all is reported as `foreign` and left untouched; a file whose marker no longer matches its own current content is reported as `drifted` and also left untouched -- in both cases only `--force` overwrites it. `--target global` combined with any provider other than `claude` fails with `usage-error` (cursor/copilot/agentsmd have no global-scope concept). Never runs unless explicitly invoked -- `adrpy-skills` is a separate entry point from `adrpy` and is never called by it.

## Arguments

### `--provider` *(optional, string)*

Comma-separated list of providers to install for: `claude`, `cursor`, `copilot`, `agentsmd`. Defaults to `all` (every bundled provider) when omitted.

### `--skill` *(optional, string)*

Comma-separated list of skills to install: `comment-audit`, `decision-log`, `pre-release-audit`. Defaults to `all` (every bundled skill) when omitted.

### `--target` *(optional, string)*

`project` (default) writes under `--path`; `global` writes under your own home directory (only meaningful for `claude` -- every other provider fails with `usage-error` under `--target global`).

### `--path` *(optional, string)*

Repository root to install into. Defaults to `.`. Only meaningful for `--target project`.

### `--force` *(optional, switch)*

Overwrites a `foreign` or `drifted` file/block instead of skipping it. Presence-only: pass just `--force`, not `--force true/false`.

## Failure codes

| Code | Condition |
|---|---|
| `usage-error` | An unknown `--provider` or `--skill` value was given, or `--target global` was combined with a provider that has no global-scope concept (anything but `claude`). |
| `io-error` | A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |

## Example

```bash
adrpy-skills install --skill decision-log,pre-release-audit --provider claude,cursor
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy-skills help install` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
