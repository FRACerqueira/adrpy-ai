<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy reject`

Marks a `Proposed` decision `Rejected`.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Marks a Proposed decision (or a migrated placeholder) Rejected, after the same repository validation and family rules as approve (doc/lifecycle.md). When the target is a successor created by supersede, its predecessor's Superseded cell is reverted first and named in `undone_predecessor`. Both files are prepared before either is written; if only the predecessor could be written, the failure names what was and was not written and the Rejected row to put in this decision by hand (data.applied, data.pending, data.repair).

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--file` | `-f` | yes | string | Path to the decision file. A bare name with no extension gets '.md' appended. |
| `--refdate` | `-r` | no | string | Reference date (YYYY-MM-DD); defaults to today. Must not be in the future or before this decision's own creation date (refdate-invalid-format/refdate-in-future/refdate-before-history). |

## Failure codes

| Code | Condition |
|---|---|
| `already-accepted` | This decision is already Accepted; run undo first to reconsider it. |
| `already-rejected` | This decision is already Rejected; run undo first to reconsider it (supersede needs it Accepted), unless it belongs to a rejected successor's family, whose line is final -- supersede its predecessor again. |
| `already-superseded` | This decision has already been superseded. |
| `refdate-invalid-format` | --refdate is not an ISO 8601 date (give it as YYYY-MM-DD). |
| `refdate-in-future` | --refdate is after today. |
| `refdate-before-history` | --refdate is before this decision's own creation date. |
| `reject-predecessor-write-failed` | Preparing either file, or committing the predecessor's reverted Superseded status, failed with a real OSError -- no write was made (data.failed_file names the file whose write failed). |
| `multi-file-write-partially-applied` | The predecessor's Superseded status was already reverted for real, but committing this decision's own Rejected status then failed -- data.applied names the file already reverted, data.pending this decision; the repository is then inconsistent until this decision is marked Rejected by hand, with the exact row in data.repair. |
| `interrupted` | Interrupted (Ctrl+C) after the predecessor's Superseded status was reverted but before this decision was marked Rejected -- same data as multi-file-write-partially-applied (data.applied, data.pending, data.repair). Once both are written, data.applied names both, data.pending is empty and there is no data.repair (the repository is consistent). What was written is read from the disk, so an interrupt right after a write counts it. An interrupt before the first write is reported without data. |
| `cannot-determine-root-path` | No adr-config.adrplus was found by walking up from --file. |
| `file-not-found` | --file does not point to an existing file (a bare name with no extension gets '.md' appended first). |
| `filename-not-recognized` | --file's own name matches neither naming scheme, or only migrationpattern matches it and it has no header while the repository already has a decision with a header migrate did not write (then it is not a decision; data.file). |
| `target-outside-folderadr` | --file is not inside the repository's decisions folder (folderadr); only a decision there is acted on -- move it into folderadr (then run migrate if it has no header). |
| `repository-inconsistent` | The decisions folder breaks at least one consistency rule (the same ones `adrpy check` reports); data.errors lists every one, with its file and a repair hint. Nothing is written until the repository is repaired. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `target-is-a-link` | A file this command would rewrite (--file; for reject of a successor, also the predecessor it reverts) is a symbolic link -- nothing was written (a write would replace the link, not the file it points to); give the real file (data.real_file), and check warns about the link. |
| `filename-too-long` | The name of a file this command would rewrite (--file; for reject of a successor, also the predecessor it reverts) is longer than the 234 bytes this tool can rewrite (data.filename) -- nothing was written; rename it by hand to a shorter title part, keeping its number, version, revision and any --NNN suffix. |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `family-member-superseded` | Another member of the same family has already been superseded. |
| `not-latest-version` | A newer member of this family locks this one -- only the latest member can change, unless every newer one is Rejected (data.latest_file names the newer file). |
| `io-error` | A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |
| `config-file-too-large` | The config file exceeds the 64KB size limit. |
| `config-file-empty` | The repository's adr-config.adrplus is empty (0 bytes), most likely left by an interrupted init: remove it and run init again. |
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
| `config-migrationpattern-invalid` | migrationpattern is non-empty but does not match N##:##T##[V##:##][R##:##][P##:##]; or, where a migrationpattern is set (config, installconfig, init, explore's preview) and at migrate, its T starts inside its N/V/R/P range or two of those ranges overlap (the detail names the overlap). |
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
<!-- generated:end -->

## Example

```bash
adrpy reject --file doc/adr/ADR001V01-use-postgre-sql-for-the-primary-datastore.md
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy help reject` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
