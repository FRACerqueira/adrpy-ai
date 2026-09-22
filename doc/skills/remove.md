<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills remove`

Removes one or more bundled skills for one or more AI-coding-agent providers.

## Description

Deletes the requested (provider, skill) pairs, or -- for `agentsmd` -- strips only that skill's own marked block from `AGENTS.md`, leaving the rest of the file (your own content, other skills' blocks) untouched; `AGENTS.md` itself is never deleted, even if this empties it. A `drifted` file/block (hand-edited since it was generated) is skipped, not deleted, unless `--force` is given -- reported as a warning, not a failure. Asking to remove something not currently installed is also a warning, not a failure. The one shared doc a stub-mode provider (`copilot`, `agentsmd`) points at is removed only once no remaining stub-mode provider in this same target still references it; removing a full-mode provider (`claude`, `cursor`) never touches it. `--target global` combined with any provider other than `claude` fails with `usage-error`.

## Arguments

### `--provider` *(optional, string)*

Comma-separated list of providers to remove from: `claude`, `cursor`, `copilot`, `agentsmd`. Defaults to `all`.

### `--skill` *(optional, string)*

Comma-separated list of skills to remove: `comment-audit`, `decision-log`, `pre-release-audit`. Defaults to `all`.

### `--target` *(optional, string)*

`project` (default) or `global` (`claude` only -- every other provider fails with `usage-error`).

### `--path` *(optional, string)*

Repository root to remove from. Defaults to `.`. Only meaningful for `--target project`.

### `--force` *(optional, switch)*

Removes a `drifted` file/block instead of skipping it. Presence-only.

## Failure codes

| Code | Condition |
|---|---|
| `usage-error` | An unknown `--provider` or `--skill` value was given, or `--target global` was combined with a provider that has no global-scope concept (anything but `claude`). |
| `io-error` | A write/delete failed for a reason not covered by a more specific code (permission denied, etc.). |

## Example

```bash
adrpy-skills remove --skill comment-audit --provider copilot
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy-skills help remove` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
