<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills help`

Lists every `adrpy-skills` command, or describes one of them in full.

## Description

Lists available commands, or describes one command. With no `command` and no `--full`, lists every command's name and one-line `summary` only. `--full` returns every command's full description and argument list in one call. Naming a specific `command` always returns its full description and argument list, regardless of `--full`. Fails with `usage-error` if the named `command` doesn't match any registered command.

## Arguments

### `command` *(optional, string, positional)*

Name of the command to describe (`help <command>`, no `--`).

### `--full` *(optional, switch)*

Return every command's full description and argument list at once, instead of the default summarized listing. Ignored when `command` is also given.

## Failure codes

| Code | Condition |
|---|---|
| `usage-error` | The named `command` doesn't match any registered command. |

## Example

```bash
adrpy-skills help install
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy-skills help help` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
