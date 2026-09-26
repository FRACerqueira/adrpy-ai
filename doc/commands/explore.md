<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy explore`

Lists every decision file in the repository, on a best-effort basis.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Lists every .md file under the decisions folder, recognized or not, and never refuses an inconsistent repository: it is the inventory, so what it could not read goes to `warnings` and every rule `adrpy check` would report as broken goes to `consistency.errors`. Each entry's `header.state` is `valid`, `adulterated` (it looks like this tool's header but does not parse) or `no-header`, with `header.invalid_reason` naming the parse failure for the last two. A file whose name only migrationpattern matches and that has no header is listed with `scheme` null (not a decision) once the repository has a decision with a valid header migrate did not write, and named in `warnings` with the number read from its name. A file in the decision-log folder (folderlog) that is not a decision-log entry (INDEX.md and CYCLES.md are the log's own) is named in `warnings` too: `adrpy log` refuses to write while it is there. With --migrationpattern, the result also has `migrationpattern_preview` -- the list `adrpy config --migrationpattern` would return for that pattern (file, number, version, title of each file it recognizes), its likely-misreading warnings in `warnings` -- while writing nothing: the inventory and consistency.errors still read the repository's own config.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--path` | `-p` | yes | string | Repository root directory (must contain adr-config.adrplus). |
| `--migrationpattern` | -- | no | string | A migrationpattern to preview (same syntax as `adrpy config --migrationpattern`), read instead of the repository's own for `migrationpattern_preview` only; nothing is written. An invalid one fails with config-migrationpattern-invalid, as does one that reads part of a name twice (its T starts inside its N/V/R/P range, or two of those ranges overlap; the detail names the overlap); an empty value is a usage error (there is nothing to preview). |

## Failure codes

| Code | Condition |
|---|---|
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
# List every decision in the repository
adrpy explore --path .

# Preview what a migrationpattern would read from each name, writing nothing
adrpy explore --path . --migrationpattern N00:04T05
```

A legacy name (one only `migrationpattern` matches) without a header is
listed with `scheme: null` and named in `warnings` once any file has a
valid header `migrate` did not write: it is not a decision then (see "ADR names" in
[the lifecycle](../lifecycle.md)). Before that, it is a decision with no
header, listed with `scheme: legacy`.

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy help explore` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
