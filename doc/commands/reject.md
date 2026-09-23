<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy reject`

Marks a `Proposed` decision `Rejected`.

## Description

Marks a Proposed decision as Rejected. May fail with file-not-found if --file does not point to an existing file (a bare name with no extension gets '.md' appended before this check), or cannot-determine-root-path if no adr-config.adrplus is found by walking up from it -- no write is attempted either way. If this decision is itself a successor (created by `supersede`), the predecessor's Superseded status is reverted FIRST, before this decision's own status is written -- the result's `undone_predecessor` names that file when this happens, or is null otherwise. This is two writes in sequence, not one, but in this order every failure up to and including the predecessor's own write leaves NOTHING committed at all: superseded-predecessor-not-found or reject-predecessor-write-failed (a real OSError on that write; a lock lost there surfaces the standard lock-lost instead, also with nothing committed), or -- if the scan for the predecessor's own family hits an unreadable subdirectory or a sibling needing a lossy UTF-8 decode -- family-scan-incomplete/family-scan-unreliable-encoding, all mean no write was made and the call is safely retryable from scratch. Only reject-own-write-failed-after-predecessor-reverted is a genuine partial success: the predecessor was already reverted for real when writing THIS decision's own Rejected status then failed -- `data.predecessor_file` names the file already reverted. Retrying `reject` on the same file after that specific failure is safe and completes the operation: when no member of the predecessor's family is Superseded any more (the revert already happened, or the predecessor was never marked at all -- an interrupted supersede, or a migrated placeholder), there is nothing to revert and reject proceeds straight to this decision's own write (`undone_predecessor` null). It fails with superseded-predecessor-not-found instead when some member of that family IS Superseded but not pointing at this decision (another successor took over, or a back-reference edited by hand) -- reject only ever reverts a Superseded mark that names this decision -- or when a member's header has this tool's shape but does not parse, so its status can't be read (`data.unparseable_files` names it; repair it by hand and retry). May instead fail with repository-locked (lock never acquired) or lock-lost (lost before any write) -- in both of those cases no write was made at all. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with family-scan-incomplete or family-scan-unreliable-encoding BEFORE any write (this decision's own family scan, unrelated to the predecessor lookup above) if a subdirectory under the decisions folder could not be scanned, or a sibling needed a lossy UTF-8 decode whose parsed header can't be trusted for a safety decision -- no write made in that case. The target's own title/scope/domain (re-read from its header cells, not flags) are re-validated before use -- may fail with field-contains-forbidden-character if a hand-edited or migrated source file's title carries '|', a line-break-like character, a filesystem-unsafe character (`<>:"/\|?*` or a control character), or consists entirely of whitespace/'_'/'-'; no write made in that case either. BEFORE any write, fails with one of already-accepted, already-rejected, already-superseded, not-proposed, or unexpected-status (the target's own current status makes Rejected unreachable from here) if the target isn't eligible, or family-member-superseded if another member of the same family has already been superseded -- no write is made in any of these cases.

## Arguments

### `--file` / `-f` *(required, string)*

Path to the decision file. A bare name with no extension gets '.md' appended.

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before this decision's own creation date (refdate-invalid-format/refdate-in-future/refdate-before-history).

## Failure codes

| Code | Condition |
|---|---|
| `already-accepted` | This decision is already Accepted; run undo first to reconsider it. |
| `already-rejected` | This decision is already Rejected. |
| `already-superseded` | This decision has already been superseded. |
| `not-proposed` | This decision's own status is not Proposed. |
| `unexpected-status` | This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell). |
| `refdate-invalid-format` | --refdate is not a strict ISO date (YYYY-MM-DD). |
| `refdate-in-future` | --refdate is after today. |
| `refdate-before-history` | --refdate is before this decision's own creation date. |
| `superseded-predecessor-not-found` | This decision's own predecessor (per its filename's supersede suffix) could not be found, a member of its family is Superseded but not pointing at this decision, or a member's header does not parse (data.unparseable_files) -- no write was made. |
| `reject-predecessor-write-failed` | Reverting the predecessor's Superseded status failed with a real OSError -- no write was made. |
| `reject-own-write-failed-after-predecessor-reverted` | The predecessor's Superseded status was already reverted for real, but writing this decision's own Rejected status then failed -- data.predecessor_file names the file already reverted; retry is safe. |
| `cannot-determine-root-path` | No adr-config.adrplus was found by walking up from --file. |
| `file-not-found` | --file does not point to an existing file (a bare name with no extension gets '.md' appended first). |
| `filename-not-recognized` | --file's own name matches neither naming scheme. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `folderadr-changed-after-lock-acquired` | A concurrent config change moved folderadr while this call was acquiring the repository lock -- no write was made; retry. |
| `field-contains-forbidden-character` | A free-text field contains '\|', a line-break-like character, or (for title) a filesystem-unsafe character. |
| `family-member-superseded` | Another member of the same family has already been superseded. |
| `family-scan-incomplete` | A subdirectory under the decisions folder could not be scanned -- family membership can't be trusted from an incomplete scan. |
| `family-scan-unreliable-encoding` | A sibling in the same family needed a lossy UTF-8 decode -- its parsed header can't be trusted for a safety decision. |
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
adrpy reject --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help reject` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
