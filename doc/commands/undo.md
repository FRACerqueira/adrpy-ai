<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy undo`

Reverts a decision's `Accepted`/`Rejected` status back to `Proposed`.

## Description

Reverts a decision's Accepted/Rejected status back to Proposed. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership can't be trusted from an incomplete scan; no write was made.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

## Example

```bash
adrpy undo --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help undo` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
