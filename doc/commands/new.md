[← Command Reference](INDEX.md)

# `adrpy new`

Creates a new decision, status `Proposed`.

## Description

Creates a new decision with status Proposed. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with new-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- title-uniqueness and next-number allocation can't be trusted from an incomplete scan; no write was made.

## Arguments

### `--path` / `-p` *(required, string)*

Repository root directory.

### `--title` / `-t` *(required, string)*

Title of the new decision. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character).

### `--domain` / `-d` *(optional, string)*

Optional domain header field. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character).

### `--scope` / `-s` *(optional, string)*

Optional scope header field. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character).

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future -- a brand new decision has no prior history to be before (refdate-invalid-format/refdate-in-future).

## Example

```bash
adrpy new --path . --title "Use PostgreSQL for the primary datastore" --domain data --scope backend
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help new` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
