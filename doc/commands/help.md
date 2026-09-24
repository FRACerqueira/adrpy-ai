<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy help`

Lists every command, or describes one of them in full.

## Description

Lists available commands, or describes one command. With no `command` and no --full, lists every command's name and one-line `summary` only, plus `defaults` (a CURATED SUBSET of the config fields a fresh `init` on this machine would actually produce -- not every field RepoConfig has; `template`, `migrationpattern`, `headerdisclaimer`, the 11 header-row labels, and the plugin fields are all omitted here on purpose, kept short since this is a quick-glance preview, not the full config -- `adrpy installconfig`/`adrpy config` return every field. `source` names whether `defaults` comes from this machine's own install-level config or the built-in default) and a `hint` pointing at `--full`/a specific command name for the complete contract. --full returns every command's full description and argument list in one call, the same shape this command always returned before summaries existed. Naming a specific `command` always returns its full description and argument list, regardless of --full. Fails with unknown-command if the named `command` doesn't match any registered command. The bare listing (no command, no --full) also reads this machine's install-level config for its defaults preview, so it may fail with a config-* code, or io-error, if that file exists but is invalid or unreadable -- `help <command>` and `help --full` never read it.

## Arguments

### `command` *(optional, string, positional -- NOT `--command`)*

Name of the command to describe. Positional, unlike every other command's flags: `adrpy help new`, never `adrpy help --command new` (which fails).

### `--full` *(optional, switch)*

Return every command's full description and argument list at once, instead of the default summarized listing. Ignored when `command` is also given -- a single named command is already returned in full either way.

## Failure codes

| Code | Condition |
|---|---|
| `unknown-command` | The named `command` doesn't match any registered command. |
| `io-error` | The bare listing could not read this machine's install-level config (permission denied or similar). |
| `config-file-too-large` | The config file exceeds the 64KB size limit. |
| `config-invalid-encoding` | The config file's bytes are not valid UTF-8. |
| `config-invalid-json` | The config file is not valid JSON, or its root is not a JSON object. |
| `config-missing-field` | The config is missing one or more required fields. |
| `config-unexpected-field` | The config has one or more fields this schema does not recognize. |
| `config-wrong-type` | A field's value is not the type this schema requires for it (string/integer/boolean/array of strings). |
| `config-lenseq-too-small` | lenseq is below its configured minimum (3). |
| `config-lenseq-too-large` | lenseq is above its configured maximum (6). |
| `config-lenversion-too-small` | lenversion is below its configured minimum (2). |
| `config-lenversion-too-large` | lenversion is above its configured maximum (4). |
| `config-lenrevision-negative` | lenrevision is below its configured minimum (0). |
| `config-lenrevision-too-large` | lenrevision is above its configured maximum (3). |
| `config-separator-invalid` | separator is not one of ('-', '_', '.'). |
| `config-casetransform-invalid` | casetransform is not one of the recognized case-transform names. |
| `config-field-empty` | A field that must be non-empty is an empty string. |
| `config-prefix-invalid` | prefix is not ASCII letters only, max 5 characters. |
| `config-folderadr-too-long` | folderadr exceeds 50 characters. |
| `config-folderadr-not-relative` | folderadr is absolute, drive-relative, or a UNC path -- it must be relative to the repository. |
| `config-folderlog-too-long` | folderlog exceeds 50 characters. |
| `config-folderlog-not-relative` | folderlog is absolute, drive-relative, or a UNC path -- it must be relative to the repository. |
| `config-folderadr-folderlog-overlap` | folderadr and folderlog are the same directory, or one is nested inside the other. |
| `config-template-too-long` | template exceeds 10000 characters. |
| `config-headerdisclaimer-too-long` | headerdisclaimer exceeds 100 characters. |
| `config-field-is-blank` | A field is non-empty but blank after stripping whitespace. |
| `config-field-contains-forbidden-character` | A field contains '\|' or a line-break-like character (or, for the 4 status labels, '(', ')', '<!--', '-->', or ':'; or, for headertablefields/headertablevalues, '<!--' or '-->'). |
| `config-migrationpattern-invalid` | migrationpattern is non-empty but does not match N##:##T##[V##:##][R##:##][P##:##]. |
| `config-headertitlefile-too-long` | headertitlefile exceeds 40 characters. |
| `config-headerversion-too-long` | headerversion exceeds 40 characters. |
| `config-headerrevision-too-long` | headerrevision exceeds 40 characters. |
| `config-headerscope-too-long` | headerscope exceeds 40 characters. |
| `config-headerdomain-too-long` | headerdomain exceeds 40 characters. |
| `config-headertitlestatuscreated-too-long` | headertitlestatuscreated exceeds 40 characters. |
| `config-headertitlestatuschanged-too-long` | headertitlestatuschanged exceeds 40 characters. |
| `config-headertitlestatussuperseded-too-long` | headertitlestatussuperseded exceeds 40 characters. |
| `config-headertablefields-too-long` | headertablefields exceeds 40 characters. |
| `config-headertablevalues-too-long` | headertablevalues exceeds 40 characters. |
| `config-headermigrated-too-long` | headermigrated exceeds 40 characters. |
| `config-statusnew-too-long` | statusnew exceeds 25 characters. |
| `config-statusacc-too-long` | statusacc exceeds 25 characters. |
| `config-statusrej-too-long` | statusrej exceeds 25 characters. |
| `config-statussup-too-long` | statussup exceeds 25 characters. |

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

This page mirrors the command's own `describe()` contract (the same JSON `adrpy help help` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
