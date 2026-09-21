<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy revise`

Creates a new revision (wording fix) of an `Accepted`/`Rejected` decision.

## Description

Creates a new revision (wording fix) of an Accepted/Rejected decision. May fail with file-not-found if --file does not point to an existing file (a bare name with no extension gets '.md' appended before this check), or cannot-determine-root-path if no adr-config.adrplus is found by walking up from it -- no write is attempted either way. Requires the repository's lenrevision to be > 0 (see the `config` command); fails with revision-not-configured otherwise -- true for any freshly-init'd repository. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership can't be trusted from an incomplete scan; no write was made. May also fail with family-scan-unreliable-encoding (data.unreliable_files names the affected file(s)) if a sibling needed a lossy UTF-8 decode -- its parsed header can't be trusted for a safety decision either, the same reasoning as an unreadable subdirectory; no write was made. The target's own title/scope/domain (all re-read from its header cells, not flags -- this command has none for scope/domain) are re-validated before use -- may fail with field-contains-forbidden-character if a hand-edited or migrated source file carries '|', a line-break-like character in any of the three, a filesystem-unsafe character in title specifically (`<>:"/\|?*` or a control character; title lands inside an actual filename component, not just a header-table cell), or title consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a file the tool can never recognize again. Fails with family-not-found if this decision's own family can't be resolved, or lenrevision-too-small-for-new-revision (data.new_revision/data.lenrevision) if the next revision number doesn't fit the configured width -- no write is made either way. If this isn't the latest version/revision in its family (and isn't the one documented branch-off-a-rejected-latest exception), fails with not-latest-version (data names the actual latest member). Fails with one of still-proposed, already-superseded, not-proposed, or unexpected-status if the target isn't eligible, or family-member-superseded/family-member-pending if another member of the same family has already been superseded or is still unresolved (Proposed). Fails with file-already-exists (data.file names it) if the resulting filename already exists on disk. No write is made in any of these cases.

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
