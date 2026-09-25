<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills remove`

Removes one or more bundled skills for one or more AI-coding-agent providers.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Deletes each requested (provider, skill) pair -- for agentsmd, only that skill's own marked block, never AGENTS.md itself -- and the shared doc once nothing in the target still references it. A foreign, drifted or malformed file or block, or an indented block whose marker still matches, is skipped unless --force is given; any other indented copy is your own text and never touched (see doc/skills/README.md). --target global works with the claude provider only.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--provider` | `-p` | no | string | Comma-separated list of providers to remove from: claude, cursor, copilot, agentsmd. Defaults to 'all' -- or, with --target global, to every provider that has a global scope (claude). |
| `--skill` | `-s` | no | string | Comma-separated list of skills to remove: adrpy, decision-log, pre-release-audit, or one no longer shipped that an older version installed (comment-audit). Defaults to 'all', which covers both. |
| `--target` | `-t` | no | string | 'project' (default) or 'global' (claude only -- every other provider fails with usage-error). |
| `--path` | -- | no | string | Repository root to remove from. Defaults to '.'. Only meaningful for --target project. |
| `--force` | `-f` | no | switch | Removes a 'drifted', 'foreign', or (agentsmd) 'malformed' or 'indented' file/block instead of skipping it. Presence-only. |
| `--allow-external-links` | -- | no | switch | Allows a file this call writes or removes to resolve, through a junction or symlink, outside the target (--path, or the home directory for --target global) -- e.g. a dotfiles setup linking .claude/skills elsewhere. Without it, such a call fails with path-outside-repository before touching anything. Presence-only. |

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory (never created) -- nothing was written. |
| `path-outside-repository` | A file this call would write or remove resolves, through a junction or symlink, outside the target (data.file/data.resolved name it) and --allow-external-links was not given -- nothing was written or removed. |
| `usage-error` | An unknown --provider, --skill, or --target value was given (--target accepts only 'project'/'global'), or --target global was combined with a provider that has no global-scope concept (anything but claude). |
| `io-error` | A read, write or delete failed (permission denied, full disk, a file over the 10MB read limit, or a file that is not valid UTF-8 -- the detail names it). data.removed/data.skipped list what this same call had already deleted before the failure, and warnings carries the warnings already collected -- the same shapes as the success result, as far as the call got. |
| `interrupted` | Interrupted (Ctrl+C) partway through; data.removed/data.skipped and warnings report what was already done, as for io-error. |
<!-- generated:end -->

## Example

```bash
adrpy-skills remove --skill pre-release-audit --provider copilot

# Remove the no-longer-shipped comment-audit skill an older version installed
adrpy-skills remove --skill comment-audit
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy-skills help remove` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
