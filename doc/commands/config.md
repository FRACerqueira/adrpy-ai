<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy config`

Reads or updates an existing repository's own `adr-config.adrplus`.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

With no field flags, reads the repository's adr-config.adrplus back (the result has a `config` key); otherwise updates only the fields passed (the result has `updated_fields` and no `config` key). Changing a guarded field -- folderadr, folderlog, a status label, separator, prefix or migrationpattern -- validates the repository first and is refused while it would orphan, reclassify or adopt existing files (ADR004V02, ADR007V01). Setting migrationpattern also returns `migrationpattern_preview` (file, number, version, title of each file it recognizes); after setting it, `adrpy explore --path .` shows the same before `adrpy migrate`. `activeplugins` is never read or written.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--path` | -- | yes | string | Repository root directory. |
| `--folderadr` | -- | no | string | Relative path to the decisions folder, max 50 characters; cannot be empty, absolute, escape the repository, or resolve to the repository root itself. |
| `--folderlog` | -- | no | string | Relative path to the decision-log directory (ADR007V01), max 50 characters; cannot be empty, absolute, escape the repository, or be the same as (or nested inside/around) folderadr (config-folderadr-folderlog-overlap). Defaults to folderadr's own parent sibling 'decision-log' when omitted from a hand-edited config written before this field existed. |
| `--migrationpattern` | -- | no | string | Positional pattern for the legacy naming scheme (N##:##T##[V##:##][R##:##][P##:##]): N is the number's start:length in the name without '.md', T where the title starts (after the separator), V/R/P the version's, revision's and prefix's start:length, positions from 00 -- e.g. 'N00:04T05' for `0001-title.md`, 'N00:04T04' for `0001Title.md`. The result lists what it recognizes (migrationpattern_preview) and warns about a likely misreading; after setting it, `adrpy explore --path .` shows the same before `adrpy migrate`. An empty value (--migrationpattern "") clears it. Like any change to it, clearing is refused (status-or-separator-change-blocked-by-existing-decisions) while a LEGACY-scheme decision that already has a header (migrated) would lose recognition; hand-written files it only matches by name do not block it. |
| `--template` | -- | no | string | Default template content for a new decision's body, max 10000 characters; a too-long value fails with config-template-too-long. The stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that. |
| `--prefix` | -- | no | string | ASCII letters only, max 5 characters; every decision name starts with it (compared case-insensitively), so it is guarded like --separator. The stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that. |
| `--separator` | -- | no | string | One of ('-', '_', '.'). |
| `--casetransform` | -- | no | string | One of ('CamelCase', 'PascalCase', 'SnakeCase', 'KebabCase'). |
| `--statusnew` | -- | no | string | Status label shown in the header table, max 25 characters; cannot be empty, contain '\|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to. |
| `--statusacc` | -- | no | string | Status label shown in the header table, max 25 characters; cannot be empty, contain '\|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to. |
| `--statusrej` | -- | no | string | Status label shown in the header table, max 25 characters; cannot be empty, contain '\|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to. |
| `--statussup` | -- | no | string | Status label shown in the header table, max 25 characters; cannot be empty, contain '\|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to. |
| `--headerdisclaimer` | -- | no | string | Header disclaimer text, max 100 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headertitlefile` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headerversion` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headerrevision` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headerscope` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headerdomain` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headertitlestatuscreated` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headertitlestatuschanged` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headertitlestatussuperseded` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--headertablefields` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. Also cannot contain '<!--' or '-->' -- these two build the header's table row, where an HTML comment is the migrated-header marker. |
| `--headertablevalues` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. Also cannot contain '<!--' or '-->' -- these two build the header's table row, where an HTML comment is the migrated-header marker. |
| `--headermigrated` | -- | no | string | Header row label, max 40 characters; cannot be empty, contain '\|', or contain a line-break-like character. |
| `--lenseq` | -- | no | integer | Integer between 3 and 6 (inclusive); a non-integer value fails with field-not-an-integer. |
| `--lenversion` | -- | no | integer | Integer between 2 and 4 (inclusive); a non-integer value fails with field-not-an-integer. |
| `--lenrevision` | -- | no | integer | Integer between 0 and 3 (inclusive); a non-integer value fails with field-not-an-integer. |
| `--disableplugins` | -- | no | boolean | 'true' or 'false'; anything else fails with field-not-a-boolean. |

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory. |
| `config-not-found` | --path's own directory has no adr-config.adrplus. |
| `field-not-an-integer` | An integer field's own value is not a valid integer. |
| `field-not-a-boolean` | --disableplugins is not 'true' or 'false'. |
| `repository-inconsistent` | A guarded field is being changed and the decisions folder breaks at least one consistency rule (the same ones `adrpy check` reports); data.errors lists every one, with its file and a repair hint. Nothing is written until the repository is repaired. |
| `folderadr-change-blocked-by-existing-decisions` | --folderadr can only be changed while the OLD folder has no recognized decisions yet. |
| `folderadr-change-scan-incomplete` | A subdirectory under the NEW folderadr could not be scanned while checking a --folderadr change. |
| `folderadr-change-would-adopt-unrelated-files` | The NEW folderadr already holds a file that would newly parse as a decision. |
| `folderadr-folderlog-alias-same-directory` | folderadr and folderlog resolve to the same real directory (or one nested inside the other), typically via a symlink or junction. |
| `folderlog-change-blocked-by-existing-entries` | --folderlog can only be changed while the OLD directory has no decision-log entries yet. |
| `folderlog-change-would-adopt-unrelated-files` | The NEW folderlog already holds a file that would newly parse as a decision-log entry. |
| `log-directory-contains-unrecognized-file` | The OLD or NEW folderlog contains a .md file that does not parse as a valid decision-log entry. |
| `log-scan-incomplete` | A subdirectory under the OLD or NEW folderlog could not be scanned while checking a --folderlog change. |
| `status-or-separator-change-blocked-by-existing-decisions` | A status-label/--separator/--prefix change would break recognition of an existing decision, or a --migrationpattern change that of a legacy-scheme decision that already has a header (migrated). |
| `separator-change-would-adopt-unrelated-files` | --separator would make a file NOT currently recognized as a decision newly parse as one. |
| `prefix-change-would-adopt-unrelated-files` | --prefix would make a file NOT currently recognized as a decision newly parse as one (data.adopted_files). |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `io-error` | The write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |
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

An empty value (`--migrationpattern ""`) clears the pattern. Clearing is a
change like any other: it is refused
(`status-or-separator-change-blocked-by-existing-decisions`) while a
legacy-scheme decision that already has a valid header (one already
migrated) would lose recognition. A legacy name the pattern matches that
has no header yet does not block it, so a wrong pattern can still be fixed
before `migrate` runs.

`lenseq`, `lenversion` and `lenrevision` are not guarded: narrowing one
below a number already on disk succeeds, and the mismatch shows up at the
next command that numbers a new file (see "What each command requires" in
[the lifecycle](../lifecycle.md)).

## Example

```bash
# Read the current config
adrpy config --path .

# Update one field
adrpy config --path . --lenrevision 2

# Clear the migration pattern (no migrated legacy-scheme decision may exist)
adrpy config --path . --migrationpattern ""
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy help config` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
