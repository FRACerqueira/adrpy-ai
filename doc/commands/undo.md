<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy undo`

Reverts a decision's `Accepted`/`Rejected` status back to `Proposed`.

## Description

Reverts a decision's Accepted/Rejected status back to Proposed. May fail with file-not-found if --file does not point to an existing file (a bare name with no extension gets '.md' appended before this check), or cannot-determine-root-path if no adr-config.adrplus is found by walking up from it -- no write is attempted either way. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership can't be trusted from an incomplete scan; no write was made. May also fail with family-scan-unreliable-encoding (data.unreliable_files names the affected file(s)) if a sibling needed a lossy UTF-8 decode -- its parsed header can't be trusted for a safety decision either, the same reasoning as an unreadable subdirectory; no write was made. The target's own title/scope/domain (re-read from its header cells, not flags) are re-validated before use -- may fail with field-contains-forbidden-character if a hand-edited or migrated source file's title carries '|', a line-break-like character, a filesystem-unsafe character (`<>:"/\|?*` or a control character), or consists entirely of whitespace/'_'/'-'.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

## Example

```bash
adrpy undo --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help undo` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
