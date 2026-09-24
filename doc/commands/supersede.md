<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy supersede`

Marks an `Accepted` decision `Superseded` and creates its successor.

## Description

Marks an Accepted decision as Superseded and creates its successor. May fail with file-not-found if --file does not point to an existing file (a bare name with no extension gets '.md' appended before this check), or cannot-determine-root-path if no adr-config.adrplus is found by walking up from it -- no write is attempted either way. Fails with not-latest-version (data names the newer file) if a newer member of the family locks this one: only the latest member is alive, unless every newer one is Rejected (see doc/lifecycle.md). Refuses with family-member-superseded if another member of the same family has already been superseded, or family-member-pending if another member is still unresolved (Proposed) -- no write is made either way. This is two writes, not one: both files are prepared first, then committed successor first: a failure preparing either file or creating the successor (supersede-successor-write-failed) means nothing was written. A failure marking the predecessor Superseded afterward (multi-file-write-partially-applied) means success=false even though the successor already exists -- that code's own `data.applied` names it, and `data.pending` the predecessor, still Accepted; --resume failing to mark the predecessor reports the same code. The successor keeps its number on disk, so no later `new` can take it; re-run with --resume to finish: it finds that successor (the existing file whose supersede suffix points back at this decision), marks only the predecessor, and says so in `warnings`. Without --resume, any existing non-Rejected successor pointing back at this decision -- left by that failure -- is refused with supersede-successor-already-exists (data.file/data.files name it) instead of being guessed at: reject it to create a new successor, or --resume to use it (one approved since must be undone back to Proposed first -- neither reject nor --resume accepts an Accepted successor; one itself superseded since needs its own successor rejected first, which reverts it -- that successor undone first if it was approved, repeating down the chain if it was itself superseded -- then undo if it had been approved). Only a file with a later sequence number than this decision counts as its successor; one pointing back from the same number (itself or its own family) or a lower one is ignored. A Rejected successor is the normal end of an earlier attempt and never counts. --resume itself fails with supersede-orphaned-successor-not-resumable (data.files names what was found) unless exactly one such successor exists and it is still Proposed with its own Created status and date, and with refdate-before-history if --refdate is before that successor's creation; no write is made in any of these cases. Rejecting a still-Proposed successor directly works too: with no member of this decision's family marked Superseded, reject has nothing to revert. May also fail with family-scan-incomplete or supersede-successor-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- family membership and successor-number allocation can't be trusted from an incomplete scan; no write was made either way. A sibling whose header does not parse is left out of the family rules and reported in `warnings` (see doc/lifecycle.md). A file pointing back at this decision whose header does not parse is not guessed at: supersede refuses with that header's parse-failure code and names the file in data.file. The successor's own title -- the predecessor's own filename segment, re-validated before use, unless --title overrides it (see its own argument description) -- may fail with field-contains-forbidden-character if it carries '|', a line-break-like character, a filesystem-unsafe character (`<>:"/\|?*` or a control character; the successor's title lands inside an actual filename component, not just a header-table cell), or consists entirely of whitespace/'_'/'-' (e.g. '-' or '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a successor the tool can never recognize again; no write is made. Fails with one of still-proposed, already-rejected, already-superseded, not-proposed, or unexpected-status (the target's own current status makes Superseded unreachable from here) if the target isn't eligible -- no write is made. Fails with file-already-exists (data.file names it) if the successor's own resulting filename already exists on disk when it is created -- no write is made either.

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

### `--resume` *(optional, switch)*

Finish an earlier supersede of this decision onto the successor it already created, marking only the predecessor -- see the description above for exactly when that is allowed. Cannot be combined with --title, --scope or --domain (usage-error): the existing successor is kept as it was created. Presence-only.

## Failure codes

| Code | Condition |
|---|---|
| `still-proposed` | This decision is still Proposed; it must be approved first (or rejected, for undo, version and revise). |
| `already-rejected` | This decision is already Rejected; run undo first to reconsider it (supersede needs it Accepted), unless it belongs to a rejected successor's family, whose line is final -- supersede its predecessor again. |
| `already-superseded` | This decision has already been superseded. |
| `not-proposed` | This decision's own Created status is not Proposed -- no command writes that; repair its Created cell by hand. |
| `unexpected-status` | This decision's own update status is not a recognized value (Proposed/Accepted/Rejected/Superseded in the wrong cell); undo clears the Changed cell. |
| `family-member-pending` | Another member of the same family is still unresolved (Proposed). |
| `refdate-invalid-format` | --refdate is not an ISO 8601 date (give it as YYYY-MM-DD). |
| `refdate-in-future` | --refdate is after today. |
| `refdate-before-history` | --refdate is before the predecessor's own last update date (or creation date, if never updated). |
| `field-is-blank` | --scope or --domain is a raw, non-empty flag value that is blank after stripping whitespace. |
| `file-already-exists` | The successor's own resulting filename already exists on disk. |
| `title-produces-unrecognizable-filename` | The successor's own title, once case-transformed, would produce a filename this tool could never recognize again. |
| `supersede-successor-scan-incomplete` | A subdirectory under the decisions folder could not be scanned while allocating the successor's own number. |
| `multi-file-write-partially-applied` | The predecessor's own write (marking it Superseded, the SECOND of the two writes) failed -- the successor already exists (data.applied names it, data.pending the predecessor); re-run supersede with --resume to finish. |
| `supersede-successor-write-failed` | Preparing either file, or creating the successor (the FIRST of the two commits), failed -- nothing was written (data.intended_successor names the file that would have been created). |
| `supersede-orphaned-successor-not-resumable` | --resume was given, but there is not exactly one non-Rejected successor of this decision still Proposed with its own Created status and date (data.files names what was found) -- no write was made. |
| `supersede-successor-already-exists` | A non-Rejected successor already points back at this decision (data.file/data.files name it) and --resume was not given -- no write was made; reject it to create a new successor, or re-run with --resume. |
| `cannot-determine-root-path` | No adr-config.adrplus was found by walking up from --file. |
| `file-not-found` | --file does not point to an existing file (a bare name with no extension gets '.md' appended first). |
| `filename-not-recognized` | --file's own name matches neither naming scheme. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `field-contains-forbidden-character` | A free-text field contains '\|', a line-break-like character, or (for title) a filesystem-unsafe character. |
| `family-member-superseded` | Another member of the same family has already been superseded. |
| `not-latest-version` | A newer member of this family locks this one -- only the latest member can change, unless every newer one is Rejected (data.latest_file names the newer file). |
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

## Example

```bash
adrpy supersede --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md --refdate 2026-09-18
```

---

This page mirrors the command's own `describe()` contract (the same JSON `adrpy help supersede` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
