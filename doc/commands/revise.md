<img src="../../src/adrpy/icon.png" width="128" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy revise`

Creates a new revision (wording fix) of an `Accepted`/`Rejected` decision.

## Description

Creates a new revision (wording fix) of an Accepted/Rejected decision. Requires the repository's lenrevision to be > 0 (see the `config` command); fails with revision-not-configured otherwise -- true for any freshly-init'd repository. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership can't be trusted from an incomplete scan; no write was made.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before the LATEST family member's own last update date (or creation date, if never updated) -- not necessarily this file's own date, when branching off an older Rejected sibling (refdate-invalid-format/refdate-in-future/refdate-before-history).

## Example

```bash
adrpy revise --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help revise` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
