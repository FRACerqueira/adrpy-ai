<img src="../../src/adrpy/icon.png" width="64" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy reject`

Marks a `Proposed` decision `Rejected`.

## Description

Marks a Proposed decision as Rejected. If this decision is itself a successor (created by `supersede`), also reverts the predecessor's Superseded status -- the result's `undone_predecessor` names that file when this happens, or is null otherwise. This is two writes in sequence, not one: a failure reverting the predecessor (superseded-predecessor-not-found, reject-predecessor-write-failed, or -- if the scan for the predecessor's own family hits an unreadable subdirectory -- family-scan-incomplete) means success=false even though this decision's OWN status was already committed to Rejected -- each of those three codes' own `data.file`/`data.status` names the file already mutated despite the overall failure (a lock lost before this SECOND write also surfaces reject-predecessor-write-failed, not lock-lost). May instead fail with repository-locked (lock never acquired) or lock-lost (lost before the FIRST write) -- in both of those cases no write was made at all. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete BEFORE the first write (this decision's own family scan, unrelated to the predecessor lookup above) if a subdirectory under the decisions folder could not be scanned -- no write made in that case.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before this decision's own creation date (refdate-invalid-format/refdate-in-future/refdate-before-history).

## Example

```bash
adrpy reject --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help reject` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
