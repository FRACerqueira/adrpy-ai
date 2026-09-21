<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy approve`

Marks a `Proposed` decision `Accepted`.

## Description

Marks a Proposed decision as Accepted. May fail with file-not-found if --file does not point to an existing file (a bare name with no extension gets '.md' appended before this check), or cannot-determine-root-path if no adr-config.adrplus is found by walking up from it -- no write is attempted either way. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership can't be trusted from an incomplete scan; no write was made. May also fail with family-scan-unreliable-encoding (data.unreliable_files names the affected file(s)) if a sibling needed a lossy UTF-8 decode -- its parsed header can't be trusted for a safety decision either, the same reasoning as an unreadable subdirectory; no write was made. The target's own title/scope/domain (re-read from its header cells, not flags) are re-validated before use -- may fail with field-contains-forbidden-character if a hand-edited or migrated source file's title carries '|', a line-break-like character, a filesystem-unsafe character (`<>:"/\|?*` or a control character), or consists entirely of whitespace/'_'/'-' -- this command never renames the file itself, but rewrites its header with the same fields a later rename-capable command (version/revise/supersede) would also need to trust. Fails with one of already-accepted, already-rejected, already-superseded, not-proposed, or unexpected-status (the target's own current status makes Accepted unreachable from here) if the target isn't eligible, or family-member-superseded if another member of the same family has already been superseded -- no write is made in any of these cases.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before this decision's own creation date (refdate-invalid-format/refdate-in-future/refdate-before-history).

## Example

```bash
adrpy approve --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help approve` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
