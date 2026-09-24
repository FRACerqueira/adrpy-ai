<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy migrate`

Adds an adrpy-compliant header to existing, hand-written decision files.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Adds an adrpy header with blank status cells (a migrated placeholder) to every hand-written decision file matching the repository's migrationpattern, which must be set in this repository's config or come from the install-level config's fallback. It is a one-time step, refused as a whole when a file already has a valid header migrate did not write (checked first, before anything is written); a fallback value is then persisted into adr-config.adrplus (reported as migrationpattern_persisted) and survives a later refusal, in which case no decision file is touched. It is also refused as a whole when a scanned file has a damaged header, carries a supersede suffix, shares a number with another or cannot be read. Files are then migrated one by one; if any fails, data.results names every file's outcome.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--path` | `-p` | yes | string | Repository root directory. |

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory. |
| `config-not-found` | --path's own directory has no adr-config.adrplus. |
| `migration-pattern-not-configured` | Both the repository's own migrationpattern and the install-level config's own fallback are empty. |
| `field-contains-forbidden-character` | A candidate's own title (sourced from its raw legacy filename) contains '\|', a line-break-like character, a filesystem-unsafe character, or consists entirely of whitespace/'_'/'-' -- a per-file failure, not a whole-batch abort. |
| `migration-scan-failed` | A candidate's own header could not even be read (permission denied or similar) -- refuses the whole run. |
| `migration-scan-incomplete` | A subdirectory under the decisions folder could not be scanned -- refuses the whole run. |
| `migration-successor-files-exist` | A scanned file already carries a supersede suffix (--NNN; data.files) -- a supersede chain is created by this tool only; refuses the whole run. |
| `migration-duplicate-numbers-exist` | Two or more scanned files share a number, version and revision (a missing revision counts as 0; data.files) -- refuses the whole run; rename them so each has its own. |
| `migration-invalid-headers-exist` | A scanned file looks like it carries this tool's header (a `\|Adr-Plus ` row, an exact `\|--\|--\|` line or a NUL byte in its first 12 lines) but it does not parse (data.files) -- refuses the whole run; repair or remove it by hand. |
| `already-tool-created-adrs-exist` | At least one scanned file already has a valid header migrate did not write (AdrPlus or adrpy; data.files) -- refuses the whole run, checked before migrationpattern is needed or persisted from the fallback; the files still without a header get one by hand. |
| `no-decisions-found` | No .md files matching a recognized naming scheme were found. |
| `no-eligible-files-to-migrate` | Every recognized file already has a header (migrated or tool-created) -- nothing needs migration. |
| `migration-write-failed` | At least one candidate failed to write -- data.results names every candidate's own outcome. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `io-error` | A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |
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
<!-- generated:end -->

## `migrationpattern` syntax

`migrationpattern` says where the parts of a legacy file name are, by
position: `N<pos>:<len>T<pos>`, optionally followed by `V<pos>:<len>`,
`R<pos>:<len>` and `P<pos>:<len>`, always in that order (N, T, V, R, P).
Every `<pos>` and `<len>` is exactly two digits, and positions count from
0 in the file name without `.md`.

| Part | Required | Reads |
|---|---|---|
| `N##:##` | yes | The decision number: the ASCII digits at that position and length. |
| `T##` | yes | The title: from that position to the end of the name. |
| `V##:##` | no | The version (ASCII digits); without it, the version is 0. |
| `R##:##` | no | The revision (ASCII digits); without it, the revision is 0. |
| `P##:##` | no | A prefix (any characters). |

A name too short for a part, or with anything but digits where `N`, `V`
or `R` expects them, is not a legacy ADR name. The current naming scheme
is always tried first, so the pattern only reads names that are not
already ADR names (see "ADR names" in [the lifecycle](../lifecycle.md)).

- `N00:04T05` reads `0001-use-postgres.md` as decision 1, title `use-postgres`.
- `N04:04T13V10:02P00:03` reads `ADR-0007-v02-use-postgres.md` as decision 7,
  version 2, prefix `ADR`, title `use-postgres`.

## Example

```bash
adrpy migrate --path .
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy help migrate` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
