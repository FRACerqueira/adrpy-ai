<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← adrpy-skills](README.md)

# `adrpy-skills help`

Lists every `adrpy-skills` command, or describes one of them in full.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Lists every adrpy-skills command with its one-line summary. Naming a `command`, or passing --full, returns the full contract (description, arguments, failure_codes) instead.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `command` (positional) | -- | no | string | Name of the command to describe. |
| `--full` | -- | no | switch | Return every command's full description and argument list at once, instead of the default summarized listing. Ignored when `command` is also given. |

## Failure codes

| Code | Condition |
|---|---|
| `usage-error` | An unrecognized argument, or more than one command name, was given. |
| `unknown-command` | The named `command` doesn't match any registered command. |
<!-- generated:end -->

## Example

```bash
adrpy-skills help install
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy-skills help help` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
