<img src="../../src/adrpy/icon.png" width="128" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy help`

Lists every command, or describes one of them in full.

## Description

Lists available commands, or describes one command. With no `command` and no --full, lists every command's name and one-line `summary` only, plus `defaults` (the config fields a fresh `init` on this machine would actually produce -- `source` names whether that comes from this machine's own install-level config or the built-in default) and a `hint` pointing at `--full`/a specific command name for the complete contract. --full returns every command's full description and argument list in one call, the same shape this command always returned before summaries existed. Naming a specific `command` always returns its full description and argument list, regardless of --full.

## Arguments

### `--command` *(optional, string, positional)*

Name of the command to describe.

### `--full` *(optional, switch)*

Return every command's full description and argument list at once, instead of the default summarized listing. Ignored when `command` is also given -- a single named command is already returned in full either way.

## Example

```bash
# Describe one command in full
adrpy help new

# List every command, summarized
adrpy help

# List every command's full contract at once
adrpy help --full
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help help` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
