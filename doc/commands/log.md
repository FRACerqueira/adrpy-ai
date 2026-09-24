<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy log`

Writes a decision-log entry -- the lighter-weight sibling of a formal ADR.

<!-- generated:start -->
<!-- Generated from describe() by scripts/generate_command_docs.py; edit the command, not this block. -->

## Description

Writes a decision-log entry under folderlog -- the lighter-weight sibling of an ADR, for an event worth recording that is not an architectural decision (see doc/decision-log-workflow.md) -- and regenerates the log's INDEX.md. It owns only the mechanics: every value is an argument, checked before the write, and the result is {created, round, warnings}, `round` being allocated for audit-finding/doc-drift. An entry already written stays on disk when the index regeneration after it fails; data.file then names it.

## Arguments

| Argument | Alias | Required | Type | Description |
|---|---|---|---|---|
| `--path` | `-p` | yes | string | Repository root directory. |
| `--classification` | `-c` | yes | string | One of: audit-finding, retraction, doc-drift, accepted-divergence, scope-note, deferred, risk-accepted, investigation, process-exception. audit-finding/doc-drift additionally require --front/--severity/--resolution (and accept optional --round); deferred additionally requires --reopenwhen; every other value accepts none of those five flags (usage-error if any are passed). |
| `--scope` | `-s` | yes | string | The module/command/concern this entry is about, reusing the project's own vocabulary. Valid kebab-case only -- lowercase letters/digits, single hyphens, no '/', '\', or embedded '--' (log-scope-invalid); becomes a literal segment of the entry's own filename. |
| `--slug` | -- | yes | string | A few kebab-case words identifying this specific entry -- lowercase letters/digits only, single hyphens between words, no leading/trailing/double hyphens (log-slug-invalid). What actually guarantees the filename is unique. |
| `--summary` | -- | yes | string | One-line summary -- becomes the entry's own '#' heading. Cannot contain '\|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank). |
| `--body` | -- | yes | string | Free-form body text, written below the heading (and the structured line, if any). |
| `--refdate` | `-r` | no | string | Reference date (YYYY-MM-DD) used as the entry's own filename date; defaults to today. Must not be in the future (refdate-invalid-format/refdate-in-future). |
| `--front` | -- | no | string | Required together with --severity/--resolution, only when --classification is audit-finding or doc-drift; usage-error otherwise. Which review angle found this. Cannot contain '\|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank). |
| `--severity` | -- | no | string | One of: Low, Medium, High (log-severity-invalid otherwise). Required together with --front/--resolution for audit-finding/doc-drift. |
| `--resolution` | -- | no | string | One of: Direct, Escalated, Retraction (log-resolution-invalid otherwise). Required together with --front/--severity for audit-finding/doc-drift. |
| `--round` | -- | no | integer | Only valid when --classification is audit-finding or doc-drift; usage-error otherwise. Optional even then: omit it to auto-assign the next round (highest existing Round across audit-finding/doc-drift entries, plus one) -- the safe default when starting a new round. Pass it explicitly to REUSE a round already in progress (the common case: a second finding in the same round), which auto-assignment can never do on its own. Must be a positive integer (log-round-invalid) not lower than the highest Round already recorded (log-round-too-low) -- Round never decreases. When omitted, the result's own `warnings` names the round that was auto-assigned, so an accidental new-round-instead-of-reuse is visible immediately instead of discovered later. |
| `--reopenwhen` | -- | no | string | Required, and only valid, when --classification is deferred; usage-error otherwise. The concrete, checkable condition that reopens this deferred item. Cannot contain '\|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank). |

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory. |
| `config-not-found` | --path's own directory has no adr-config.adrplus. |
| `folderadr-folderlog-alias-same-directory` | folderadr and folderlog resolve to the same real directory (or one nested inside the other), typically via a symlink or junction. |
| `log-classification-invalid` | --classification is not one of the recognized classifications. |
| `log-slug-invalid` | --slug is not valid kebab-case. |
| `log-scope-invalid` | --scope is not valid kebab-case, or contains '/' or '\'. |
| `log-severity-invalid` | --severity is not one of Low/Medium/High. |
| `log-resolution-invalid` | --resolution is not one of Direct/Escalated/Retraction. |
| `log-round-invalid` | --round is not a positive integer. |
| `refdate-invalid-format` | --refdate is not an ISO 8601 date (give it as YYYY-MM-DD). |
| `refdate-in-future` | --refdate is after today. |
| `log-round-too-low` | --round is lower than the highest Round already recorded. |
| `field-contains-forbidden-character` | summary/front/reopenwhen contains '\|' or a line-break-like character. |
| `field-is-blank` | summary/front/reopenwhen is non-empty but blank after stripping whitespace. |
| `log-directory-contains-unrecognized-file` | A file under folderlog does not match the expected filename shape, or carries an unrecognized classification, or has no content, or (checked only when this call's own --classification is audit-finding/doc-drift) is an audit-finding/doc-drift entry whose Round is missing or not a plain integer -- Round/INDEX.md can't be safely computed while it's present. |
| `log-scan-incomplete` | A subdirectory under folderlog could not be scanned. |
| `log-entry-already-exists` | An entry with this exact date/classification/scope/slug already exists -- no entry was written, but INDEX.md is regenerated so it lists the existing one (a warning says so when that regeneration itself fails). |
| `log-index-regeneration-failed` | The entry itself was written, but regenerating INDEX.md afterward failed. |
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

## Example

```bash
# A plain entry, no structured line
adrpy log --path . --classification scope-note --scope config --slug clarify-folderlog-default --summary "Clarify the folderlog default" --body "Omitted, folderlog is the decision-log sibling of folderadr."

# audit-finding/doc-drift: --front/--severity/--resolution required, --round computed automatically
adrpy log --path . --classification audit-finding --scope fs --slug retry-loop-off-by-one --summary "Retry loop stopped one attempt short" --body "Details of the fix." --front "test-adequacy audit" --severity Medium --resolution Direct

# deferred: --reopenwhen required
adrpy log --path . --classification deferred --scope security --slug posix-symlink-coverage --summary "POSIX symlink-escape coverage deferred" --body "Windows-only today." --reopenwhen "the test-adequacy audit front runs again"
```

---

The Description, Arguments and Failure codes sections are generated from the command's own `describe()` contract (the same JSON `adrpy help log` returns at runtime) by `scripts/generate_command_docs.py`; the example is written by hand.
