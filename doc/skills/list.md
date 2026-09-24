<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills list`

Reports which bundled skills are installed, for which providers, and whether any have drifted.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Reports, for every requested skill and provider, whether it is installed, whether it has drifted (null when not installed; true for a foreign, hand-edited or malformed file or block) and the resolved path; claude is reported in both project and global scope. A stub-mode provider adds one `shared-doc` row per skill. Read-only: it computes hashes but never writes.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--provider` | `-p` | no | string | Comma-separated list of providers to report on: claude, cursor, copilot, agentsmd. Defaults to 'all'. |
| `--skill` | `-s` | no | string | Comma-separated list of skills to report on: comment-audit, decision-log, pre-release-audit. Defaults to 'all'. |
| `--path` | -- | no | string | Repository root to inspect for project-scope entries. Defaults to '.'. |

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory (never created) -- nothing was written. |
| `usage-error` | An unknown --provider or --skill value was given. |
| `io-error` | A read failed (permission denied, a file over the 10MB read limit, or a file that is not valid UTF-8 -- the detail names it). |
<!-- generated:end -->

## Example

```bash
adrpy-skills list --path .
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy-skills help list` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
