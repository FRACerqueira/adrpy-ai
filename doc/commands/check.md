<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy check`

Validates every decision in the repository and lists every inconsistency found.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Validates the whole repository, read-only: every file with an ADR name under the decisions folder (any other .md is ignored) is checked against the consistency rules in doc/lifecycle.md. Succeeds with the number of decisions when every rule holds; otherwise fails with repository-inconsistent, every broken rule listed in data.errors (code, file, related_files, detail, hint), sorted by file. A .md file with no ADR name that looks like a decision (its name starts with a digit) is named in `warnings`, on success or failure, as is a file whose name only migrationpattern matches and that has no header once the repository has a decision with a valid header migrate did not write (then it is not a decision: see doc/lifecycle.md, ADR names).

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--path` | `-p` | yes | string | Repository root directory (must contain adr-config.adrplus). |

## Failure codes

| Code | Condition |
|---|---|
| `repository-inconsistent` | At least one consistency rule is broken; data.errors lists every one. |
| `merge-conflict-markers` | data.errors[].code: git merge-conflict markers in a file's 12 header lines (reported alone for that file; a supersede link to or from it is not also reported broken while the conflict exists). |
| `no-header` | data.errors[].code: a file with an ADR name has no header at all (run migrate if it predates the tool); `detail` says '0-byte file' when it is empty, left by an interrupted create (remove it). |
| `invalid-header` | data.errors[].code: a file's header does not parse; `detail` names the parse failure. |
| `invalid-status-combination` | data.errors[].code: a header's Created/Changed/Superseded cells form a combination no command writes (detail names the three cells). |
| `duplicate-number` | data.errors[].code: two files share number, version and revision (a missing revision counts as 0). |
| `pending-duplicate` | data.errors[].code: a family has more than one open Proposed decision (a migrated placeholder does not count). |
| `pending-not-live` | data.errors[].code: a Proposed decision is locked by a newer family member that is not Rejected. |
| `superseded-duplicate` | data.errors[].code: a family has more than one Superseded member. |
| `superseded-not-live` | data.errors[].code: a Superseded decision is locked by a newer family member that is not Rejected. |
| `superseded-without-successor` | data.errors[].code: a Superseded cell points at no existing, non-Rejected successor whose filename suffix names this decision. |
| `successor-without-predecessor` | data.errors[].code: a non-Rejected successor has no predecessor whose Superseded cell points back at it. |
| `multiple-live-successors` | data.errors[].code: more than one non-Rejected successor names the same predecessor. |
| `rejected-successor-family-not-final` | data.errors[].code: a member of a Rejected successor's family is not Rejected. |
| `scan-incomplete` | data.errors[].code: a directory or decision file under the decisions folder could not be read. |
| `header-invalid` | data.errors[].detail of an invalid-header entry starts with this code: the header failed structural validation, for a reason not covered by a more specific code below. |
| `adr-file-empty` | Never an invalid-header detail: a 0-byte file with an ADR name is reported as no-header (explore's header.invalid_reason is where this code appears). |
| `adr-file-too-short` | data.errors[].detail of an invalid-header entry starts with this code: the file has fewer than the 12 required header lines. |
| `adr-header-comment-not-found` | data.errors[].detail of an invalid-header entry starts with this code: line 1 (or line 12) is not the '<!-- ... -->' disclaimer comment this format requires. |
| `adr-header-invalid-format` | data.errors[].detail of an invalid-header entry starts with this code: line 2 or line 3 does not match the fixed table-header shape this format requires. |
| `adr-header-title-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Title row's own cell is missing or malformed. |
| `adr-header-version-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Version row's own cell is missing, malformed, or not a plain digit run. |
| `adr-header-revision-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Revision row's own cell is missing, malformed, or not a plain digit run. |
| `adr-header-scope-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Scope row's own cell is missing or malformed. |
| `adr-header-domain-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Domain row's own cell is missing or malformed. |
| `adr-header-status-created-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Created status row's own cell is missing or malformed. |
| `adr-header-status-updated-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Changed status row's own cell is missing or malformed. |
| `adr-header-status-superseded-not-found` | data.errors[].detail of an invalid-header entry starts with this code: the Superseded status row's own cell is missing or malformed. |
| `adr-status-supersede-format-invalid` | data.errors[].detail of an invalid-header entry starts with this code: the Superseded row's own status is set, but its successor-reference suffix (': <number>') is missing. |
| `status-line-format-invalid` | data.errors[].detail of an invalid-header entry starts with this code: a status cell's own parenthesized-date shape ('label (date)') could not be parsed at all. |
| `status-line-unknown-status` | data.errors[].detail of an invalid-header entry starts with this code: a status cell's own label text does not match any of statusnew/statusacc/statusrej/statussup, and no canonical marker is present either. |
| `status-line-date-invalid` | data.errors[].detail of an invalid-header entry starts with this code: a status cell's own parenthesized date is not a valid ISO date. |
| `field-contains-forbidden-character` | data.errors[].detail of an invalid-header entry starts with this code: the Title, Scope or Domain cell breaks a free-text rule: a '\|' (an extra cell in its row), a line-break-like character, or (for Title) a filesystem-unsafe character or no character other than whitespace, '_' or '-'. |
| `target-directory-not-found` | --path does not point to an existing directory. |
| `config-not-found` | --path's own directory has no adr-config.adrplus. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
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
<!-- generated:end -->

## Example

```bash
# Validate the repository (exit code 0 when consistent, 1 when not)
adrpy check --path .
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy help check` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
