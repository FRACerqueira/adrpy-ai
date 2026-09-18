[← Command Reference](INDEX.md)

# `adrpy explore`

Lists every decision file in the repository, on a best-effort basis.

## Description

Lists every decision file in the repository, recognized or not, on a best-effort basis: a file excluded for escaping the repository boundary, a subdirectory that could not be scanned, or a single file that could not be read are all reported via `warnings` instead of silently missing from `decisions` or failing the whole command.

## Arguments

### `--path` / `-p` *(required, string)*

Repository root directory (must contain adr-config.adrplus).

## Example

```bash
# List every decision in the repository
adrpy explore --path .
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help explore` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
