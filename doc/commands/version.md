# `adrpy version`

Creates a new major version of an `Accepted`/`Rejected` decision.

## Description

Creates a new major version of an Accepted/Rejected decision. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership can't be trusted from an incomplete scan; no write was made.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

### `--domain` / `-d` *(optional, string)*

Domain for the new version; defaults to the latest version's own value. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character).

### `--scope` / `-s` *(optional, string)*

Scope for the new version; defaults to the latest version's own value. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character).

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before the LATEST family member's own last update date (or creation date, if never updated) -- not necessarily this file's own date, when branching off an older Rejected sibling (refdate-invalid-format/refdate-in-future/refdate-before-history).

### `--empty` / `-e` *(optional, switch)*

Start from the default template instead of carrying the source's content forward. Presence-only: pass just '--empty' with no value; do not pass '--empty true/false'.

## Example

```bash
adrpy version --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md --empty
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help version` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
