<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy supersede`

Marks an `Accepted` decision `Superseded` and creates its successor.

## Description

Marks an Accepted decision as Superseded and creates its successor. May fail with file-not-found if --file does not point to an existing file (a bare name with no extension gets '.md' appended before this check), or cannot-determine-root-path if no adr-config.adrplus is found by walking up from it -- no write is attempted either way. Refuses with family-member-superseded if another member of the same family has already been superseded, or family-member-pending if another member is still unresolved (Proposed) -- no write is made either way. This is two writes in sequence, not one: a failure creating the successor (supersede-successor-write-failed) means success=false even though the predecessor was already committed to Superseded -- that code's own `data.predecessor`/`data.predecessor_status` names the file already mutated despite the overall failure (a lock lost before this SECOND write also surfaces this same code/data, not lock-lost). May instead fail with repository-locked (lock never acquired) or lock-lost (lost before the FIRST write) -- in both of those cases no write was made at all. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete or supersede-successor-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership and successor-number allocation can't be trusted from an incomplete scan; no write was made either way. May also fail with family-scan-unreliable-encoding (data.unreliable_files names the affected file(s)) if a sibling needed a lossy UTF-8 decode -- its parsed header can't be trusted for a safety decision either, the same reasoning as an unreadable subdirectory; no write was made. The successor's own title -- the predecessor's own filename segment, re-validated before use, unless --title overrides it (see its own argument description) -- may fail with field-contains-forbidden-character if it carries '|', a line-break-like character, a filesystem-unsafe character (`<>:"/\|?*` or a control character; the successor's title lands inside an actual filename component, not just a header-table cell), or consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a successor the tool can never recognize again; no write is made. Fails with one of still-proposed, already-rejected, already-superseded, not-proposed, or unexpected-status (the target's own current status makes Superseded unreachable from here) if the target isn't eligible -- no write is made. Fails with file-already-exists (data.file names it) if the successor's own resulting filename already exists on disk -- no write is made either. If the PREDECESSOR's own write (marking it Superseded, the FIRST of the two writes) fails with an OSError, that surfaces as supersede-write-failed instead of a generic io-error, for discoverability -- nothing was written in that case.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

### `--domain` / `-d` *(optional, string)*

Domain for the successor; defaults to the predecessor's own value. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank).

### `--scope` / `-s` *(optional, string)*

Scope for the successor; defaults to the predecessor's own value. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank).

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before the predecessor's own last update date (or creation date, if never updated) (refdate-invalid-format/refdate-in-future/refdate-before-history).

### `--title` / `-t` *(optional, string)*

Title for the successor; defaults to the predecessor's own filename-segment title (unlike --scope/--domain, this default is NOT re-editable via the header's prose title -- see the description above). Cannot contain '|' or a line-break-like character, or a filesystem-unsafe character (`<>:"/\|?*` or a control character -- title lands inside an actual filename component, not just a header-table cell); also cannot consist entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a successor the tool can never recognize again (field-contains-forbidden-character), or be blank (field-is-blank).

## Example

```bash
adrpy supersede --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md --refdate 2026-09-18
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help supersede` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
