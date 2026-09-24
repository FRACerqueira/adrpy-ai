<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy revise`

Creates a new revision (wording fix) of an `Accepted`/`Rejected` decision.

## Description

Creates a new revision (wording fix) of an Accepted/Rejected decision. May fail with file-not-found if --file does not point to an existing file (a bare name with no extension gets '.md' appended before this check), or cannot-determine-root-path if no adr-config.adrplus is found by walking up from it -- no write is attempted either way. Requires the repository's lenrevision to be > 0 (see the `config` command); fails with revision-not-configured otherwise -- true for any freshly-init'd repository. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed by another process before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership can't be trusted from an incomplete scan; no write was made. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). The target's own title/scope/domain (all re-read from its header cells, not flags -- this command has none for scope/domain) are re-validated before use -- may fail with field-contains-forbidden-character if a hand-edited or migrated source file carries '|', a line-break-like character in any of the three, a filesystem-unsafe character in title specifically (`<>:"/\|?*` or a control character; title lands inside an actual filename component, not just a header-table cell), or title consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a file the tool can never recognize again. Fails with family-not-found if this decision's own family can't be resolved, or lenrevision-too-small-for-new-revision (data.new_revision/data.lenrevision) if the next revision number -- the one after the highest revision this version already holds, whatever file holds it -- doesn't fit the configured width -- no write is made either way. Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Fails with rejected-successor-is-final if the target belongs to the family of a successor that was rejected. Fails with one of still-proposed, already-superseded, not-proposed, or unexpected-status if the target isn't eligible, or family-member-superseded/family-member-pending if another member of the same family has already been superseded or is still unresolved (Proposed). Fails with file-already-exists (data.file names it) if the resulting filename already exists on disk. No write is made in any of these cases.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before the LATEST family member's own last update date (or creation date, if never updated) -- not necessarily this file's own date, when branching off an older Rejected sibling (refdate-invalid-format/refdate-in-future/refdate-before-history).

## Failure codes

| Code | Condition |
|---|---|
| `still-proposed` | This decision must be Accepted or Rejected before a new revision can be created. |
| `already-superseded` | This decision has already been superseded. |
| `not-proposed` | This decision's own Created status is not Proposed -- no command writes that; repair its Created cell by hand. |
| `unexpected-status` | This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell); undo clears the Changed cell. |
| `family-member-pending` | Another member of the same family is still unresolved (Proposed). |
| `family-not-found` | This decision's own family could not be resolved. |
| `refdate-invalid-format` | --refdate is not an ISO 8601 date (give it as YYYY-MM-DD). |
| `refdate-in-future` | --refdate is after today. |
| `refdate-before-history` | --refdate is before the LATEST family member's own last update date (or creation date, if never updated). |
| `file-already-exists` | The new revision's own resulting filename already exists on disk (data.file names it). |
| `lenrevision-too-small-for-new-revision` | The next revision number does not fit in the configured lenrevision width. |
| `not-latest-version` | A newer member of this family locks this one -- only the latest member can change, unless every newer one is Rejected (data.latest_file names the newer file). |
| `revision-not-configured` | This repository's config has lenrevision == 0. |
| `title-produces-unrecognizable-filename` | The new revision's own title, once case-transformed, would produce a filename this tool could never recognize again. |
| `cannot-determine-root-path` | No adr-config.adrplus was found by walking up from --file. |
| `file-not-found` | --file does not point to an existing file (a bare name with no extension gets '.md' appended first). |
| `filename-not-recognized` | --file's own name matches neither naming scheme. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `folderadr-changed-after-lock-acquired` | A concurrent config change moved folderadr while this call was acquiring the repository lock -- no write was made; retry. |
| `field-contains-forbidden-character` | A free-text field contains '\|', a line-break-like character, or (for title) a filesystem-unsafe character. |
| `family-member-superseded` | Another member of the same family has already been superseded. |
| `rejected-successor-is-final` | This decision belongs to the family of a successor that was rejected -- the end of its line; supersede its predecessor again instead (data.successor_file, data.predecessor_number). |
| `family-scan-incomplete` | A subdirectory under the decisions folder could not be scanned -- family membership can't be trusted from an incomplete scan. |
| `io-error` | A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |
| `header-invalid` | The header failed structural validation, for a reason not covered by a more specific code below. |
| `adr-file-empty` | The file has no content at all. |
| `adr-file-too-short` | The file has fewer than the 12 required header lines. |
| `adr-header-comment-not-found` | Line 1 (or line 12) is not the '<!-- ... -->' disclaimer comment this format requires. |
| `adr-header-invalid-format` | Line 2 or line 3 does not match the fixed table-header shape this format requires. |
| `adr-header-title-not-found` | The Title row's own cell is missing or malformed. |
| `adr-header-version-not-found` | The Version row's own cell is missing, malformed, or not a plain digit run. |
| `adr-header-revision-not-found` | The Revision row's own cell is missing, malformed, or not a plain digit run. |
| `adr-header-scope-not-found` | The Scope row's own cell is missing or malformed. |
| `adr-header-domain-not-found` | The Domain row's own cell is missing or malformed. |
| `adr-header-status-created-not-found` | The Created status row's own cell is missing or malformed. |
| `adr-header-status-updated-not-found` | The Changed status row's own cell is missing or malformed. |
| `adr-header-status-superseded-not-found` | The Superseded status row's own cell is missing or malformed. |
| `adr-status-supersede-format-invalid` | The Superseded row's own status is set, but its successor-reference suffix (': <number>') is missing. |
| `status-line-format-invalid` | A status cell's own parenthesized-date shape ('label (date)') could not be parsed at all. |
| `status-line-unknown-status` | A status cell's own label text does not match any of statusnew/statusacc/statusrej/statussup, and no canonical marker is present either. |
| `status-line-date-invalid` | A status cell's own parenthesized date is not a valid ISO date. |
| `config-file-too-large` | The config file exceeds the 64KB size limit. |
| `config-invalid-encoding` | The config file's bytes are not valid UTF-8. |
| `config-invalid-json` | The config file is not valid JSON, or its root is not a JSON object. |
| `config-missing-field` | The config is missing one or more required fields. |
| `config-unexpected-field` | The config has one or more fields this schema does not recognize. |
| `config-wrong-type` | A field's value is not the type this schema requires for it (string/integer/boolean/array of strings). |
| `config-lenseq-too-small` | lenseq is below its configured minimum (3). |
| `config-lenseq-too-large` | lenseq is above its configured maximum (6). |
| `config-lenversion-too-small` | lenversion is below its configured minimum (2). |
| `config-lenversion-too-large` | lenversion is above its configured maximum (4). |
| `config-lenrevision-negative` | lenrevision is below its configured minimum (0). |
| `config-lenrevision-too-large` | lenrevision is above its configured maximum (3). |
| `config-separator-invalid` | separator is not one of ('-', '_', '.'). |
| `config-casetransform-invalid` | casetransform is not one of the recognized case-transform names. |
| `config-field-empty` | A field that must be non-empty is an empty string. |
| `config-prefix-invalid` | prefix is not ASCII letters only, max 5 characters. |
| `config-folderadr-too-long` | folderadr exceeds 50 characters. |
| `config-folderadr-not-relative` | folderadr is absolute, drive-relative, or a UNC path -- it must be relative to the repository. |
| `config-folderlog-too-long` | folderlog exceeds 50 characters. |
| `config-folderlog-not-relative` | folderlog is absolute, drive-relative, or a UNC path -- it must be relative to the repository. |
| `config-folderadr-folderlog-overlap` | folderadr and folderlog are the same directory, or one is nested inside the other. |
| `config-template-too-long` | template exceeds 10000 characters. |
| `config-headerdisclaimer-too-long` | headerdisclaimer exceeds 100 characters. |
| `config-field-is-blank` | A field is non-empty but blank after stripping whitespace. |
| `config-field-contains-forbidden-character` | A field contains '\|' or a line-break-like character (or, for the 4 status labels, '(', ')', '<!--', '-->', or ':'; or, for headertablefields/headertablevalues, '<!--' or '-->'). |
| `config-migrationpattern-invalid` | migrationpattern is non-empty but does not match N##:##T##[V##:##][R##:##][P##:##]. |
| `config-headertitlefile-too-long` | headertitlefile exceeds 40 characters. |
| `config-headerversion-too-long` | headerversion exceeds 40 characters. |
| `config-headerrevision-too-long` | headerrevision exceeds 40 characters. |
| `config-headerscope-too-long` | headerscope exceeds 40 characters. |
| `config-headerdomain-too-long` | headerdomain exceeds 40 characters. |
| `config-headertitlestatuscreated-too-long` | headertitlestatuscreated exceeds 40 characters. |
| `config-headertitlestatuschanged-too-long` | headertitlestatuschanged exceeds 40 characters. |
| `config-headertitlestatussuperseded-too-long` | headertitlestatussuperseded exceeds 40 characters. |
| `config-headertablefields-too-long` | headertablefields exceeds 40 characters. |
| `config-headertablevalues-too-long` | headertablevalues exceeds 40 characters. |
| `config-headermigrated-too-long` | headermigrated exceeds 40 characters. |
| `config-statusnew-too-long` | statusnew exceeds 25 characters. |
| `config-statusacc-too-long` | statusacc exceeds 25 characters. |
| `config-statusrej-too-long` | statusrej exceeds 25 characters. |
| `config-statussup-too-long` | statussup exceeds 25 characters. |
| `repository-locked` | The repository lock could not be acquired before timing out. |
| `lock-lost` | The repository lock was acquired but reclaimed by another process before this write could commit -- no write was made; retry. |

## Example

```bash
adrpy revise --file doc/adr/ADR001V01R01-use-postgre-sql-for-the-primary-datastore.md
```

---

This page mirrors the command's own `describe()` contract (the same JSON `adrpy help revise` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
