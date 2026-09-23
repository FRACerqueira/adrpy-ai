<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills list`

Reports which bundled skills are installed, for which providers, and whether any have drifted.

## Description

Cross-product of every requested skill x every requested provider, each entry reporting `installed` (bool), `drifted` (null when not installed; otherwise true if the file/block is either `foreign` -- no `adrpy-skills` marker, meaning `install`/`remove` would refuse to touch it without `--force` -- or genuinely hand-edited since it was generated; false only when the content still matches exactly what was last generated), and the resolved file path either way. Always reports both project and global scope for `claude` (the only provider with a global-scope concept); every other provider is project-scope only. When any requested provider is stub-mode (`copilot`, `agentsmd`), one extra row per skill is included under provider `shared-doc` (project scope only) for the one shared `doc/ai-skills/<name>.md` file its stub points at -- the same shared-doc concept `install`/`remove` already report under that same provider name in their own `installed`/`removed`. Read-only in the strict sense: computes a hash to determine drift, but never writes anything back, regardless of what it finds.

## Arguments

### `--provider` / `-p` *(optional, string)*

Comma-separated list of providers to report on: `claude`, `cursor`, `copilot`, `agentsmd`. Defaults to `all`.

### `--skill` / `-s` *(optional, string)*

Comma-separated list of skills to report on: `comment-audit`, `decision-log`, `pre-release-audit`. Defaults to `all`.

### `--path` *(optional, string)*

Repository root to inspect for project-scope entries. Defaults to `.`.

## Failure codes

| Code | Condition |
|---|---|
| `usage-error` | An unknown `--provider` or `--skill` value was given. |
| `io-error` | A read failed (permission denied, a file over the 10MB read limit, or a file that is not valid UTF-8 -- the detail names it). |

## Example

```bash
adrpy-skills list --path .
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy-skills help list` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
