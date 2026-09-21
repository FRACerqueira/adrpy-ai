<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy new`

Creates a new decision, status `Proposed`.

## Description

Creates a new decision with status Proposed. May fail with target-directory-not-found if --path does not point to an existing directory, or config-not-found if that directory has no adr-config.adrplus -- no write is attempted either way. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with new-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- title-uniqueness and next-number allocation can't be trusted from an incomplete scan; no write was made. Once the scan itself succeeds, fails with title-already-exists (data.existing_file names it) if another decision already has this exact title, or file-already-exists (data.file names it) if the resulting filename happens to already exist on disk -- neither write is made.

## Arguments

### `--path` / `-p` *(required, string)*

Repository root directory.

### `--title` / `-t` *(required, string)*

Title of the new decision. Cannot contain '|' or a line-break-like character, or a filesystem-unsafe character (`<>:"/\|?*` or a control character -- unlike every other free-text field, title lands inside an actual filename component, not just a header-table cell); also cannot consist entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a file the tool can never recognize again (field-contains-forbidden-character), or be blank (field-is-blank).

### `--domain` / `-d` *(optional, string)*

Optional domain header field. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank).

### `--scope` / `-s` *(optional, string)*

Optional scope header field. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank).

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future -- a brand new decision has no prior history to be before (refdate-invalid-format/refdate-in-future).

## Example

```bash
adrpy new --path . --title "Use PostgreSQL for the primary datastore" --domain data --scope backend
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help new` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
