<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills install`

Installs one or more bundled skills for one or more AI-coding-agent providers.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Writes each requested (provider, skill) pair in the shape that provider expects: the full skill body for claude/cursor, a short stub pointing at one shared doc for copilot/agentsmd (for agentsmd, only that skill's own marked block in AGENTS.md). A file or block that is foreign (no marker), drifted (edited since it was generated) or malformed is left untouched unless --force is given, and a stub is never written while its shared doc is blocked (see doc/skills/README.md). --target global works with the claude provider only.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--provider` | `-p` | no | string | Comma-separated list of providers to install for: claude, cursor, copilot, agentsmd. Defaults to 'all' (every bundled provider) when omitted -- or, with --target global, to every provider that has a global scope (claude). |
| `--skill` | `-s` | no | string | Comma-separated list of skills to install: comment-audit, decision-log, pre-release-audit. Defaults to 'all' (every bundled skill) when omitted. |
| `--target` | `-t` | no | string | 'project' (default) writes under --path; 'global' writes under the user's own home directory (only meaningful for claude -- every other provider fails with usage-error under --target global). |
| `--path` | -- | no | string | Repository root to install into. Defaults to '.'. Only meaningful for --target project. |
| `--force` | `-f` | no | switch | Overwrites a 'foreign', 'drifted', or (agentsmd) 'malformed' file/block instead of skipping it. Presence-only: pass just '--force', not '--force true/false'. |
| `--allow-external-links` | -- | no | switch | Allows a file this call writes or removes to resolve, through a junction or symlink, outside the target (--path, or the home directory for --target global) -- e.g. a dotfiles setup linking .claude/skills elsewhere. Without it, such a call fails with path-outside-repository before touching anything. Presence-only. |

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory (never created) -- nothing was written. |
| `path-outside-repository` | A file this call would write or remove resolves, through a junction or symlink, outside the target (data.file/data.resolved name it) and --allow-external-links was not given -- nothing was written or removed. |
| `usage-error` | An unknown --provider, --skill, or --target value was given (--target accepts only 'project'/'global'), or --target global was combined with a provider that has no global-scope concept (anything but claude). |
| `io-error` | A read, write or delete failed (permission denied, full disk, a file over the 10MB read limit, or a file that is not valid UTF-8 -- the detail names it). data.installed/data.skipped list what this same call had already written before the failure, and warnings carries the warnings already collected -- the same shapes as the success result, as far as the call got. |
| `interrupted` | Interrupted (Ctrl+C) partway through; data.installed/data.skipped and warnings report what was already done, as for io-error. |
<!-- generated:end -->

## Example

```bash
adrpy-skills install --skill decision-log,pre-release-audit --provider claude,cursor
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy-skills help install` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
