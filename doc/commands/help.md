<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy help`

Lists every command, or describes one of them in full.

## Description

Lists available commands, or describes one command. With no `command` and no --full, lists every command's name and one-line `summary` only, plus `defaults` (a CURATED SUBSET of the config fields a fresh `init` on this machine would actually produce -- not every field RepoConfig has; `template`, `migrationpattern`, `headerdisclaimer`, the 11 header-row labels, and the plugin fields are all omitted here on purpose, kept short since this is a quick-glance preview, not the full config -- `adrpy installconfig`/`adrpy config` return every field. `source` names whether `defaults` comes from this machine's own install-level config or the built-in default) and a `hint` pointing at `--full`/a specific command name for the complete contract. --full returns every command's full description and argument list in one call, the same shape this command always returned before summaries existed. Naming a specific `command` always returns its full description and argument list, regardless of --full. Fails with unknown-command if the named `command` doesn't match any registered command.

## Arguments

### `command` *(optional, string, positional -- NOT `--command`)*

Name of the command to describe. Positional, unlike every other command's flags: `adrpy help new`, never `adrpy help --command new` (which fails).

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
