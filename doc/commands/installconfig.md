<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy installconfig`

Reads or updates the per-user, install-level default config (seeds new repositories, supplies a migrate fallback).

## Description

Reads or updates the per-user install-level config (ADR002V01) -- used by `init` as its default seed when no --seed/--language is given, and by `migrate` as a migrationpattern fallback when a repository's own is empty. Unlike every other command except `help`, targets no repository at all (neither --path nor --file), and so takes no --path: always operates on the one, fixed, per-user location this machine resolves to. With no field flags and no --seed, reads the current config back (read-only, no write); the result's `configured` key is false with no `config` key at all if the file doesn't exist yet -- the normal state for any installation that has never run this command, not an error -- or true with a `config` key otherwise. `updated_fields` is present as an empty list on every read too, same as `config`'s own bare-read shape -- a generic wrapper that reads `data.updated_fields` unconditionally works the same after any call, read or write. `activeplugins` is never included in that read result or accepted as a field to update -- same as the `config` command, the plugin system is out of scope for now -- but is still carried through unchanged from whatever base a write merges onto. Omitted fields keep their current value (or the built-in default's, on first write); only the fields passed are updated. A write call's result never has the `config`/`configured` keys. --seed replaces the file wholesale, same as `init --seed`, and reports every editable field in `updated_fields` since a full replace makes every one of them this call's own -- not a diff against whatever was there before. --language replaces the file wholesale too, with the built-in default's header/status labels and template swapped for that language's own -- same reporting rule as --seed applies to it.

## Arguments

### `--seed` *(optional, string)*

Path to a config JSON to replace the install-level config with wholesale, instead of merging individual field flags -- same semantics as `init --seed`. Fails with config-file-not-found if this path itself does not point to an existing file. The install-level config's schema is byte-compatible with a repository's own adr-config.adrplus, so this also covers importing one from a real installation of the reference tool's own template file directly, with no separate flag needed. Any field flag passed ALONGSIDE --seed raises usage-error -- pass one or the other -- same as `init`'s own incompatible flag combination (--seed with --language).

### `--language` *(optional, string)*

Built-in default language pack for header/status labels and the default template (one of ('en-us', 'pt-br', 'de-de', 'es-es', 'fr-fr', 'it-it', 'ja-jp', 'ko-kr', 'nl-be', 'ru-ru', 'zh-cn')), applied over the built-in default -- everything else (folderadr, separator, lenseq/lenversion/lenrevision, casetransform, migrationpattern) stays the built-in default's own value regardless of language. Replaces the file wholesale, same as --seed -- cannot be combined with --seed or with any individual field flag in the same call; usage-error either way, same rule --seed already applies to a co-passed field flag. Unlike `init --language`, this one is never blocked by an existing install-level config -- writing that config IS what this command is for.

### `--folderadr` *(optional, string)*

Relative path to the decisions folder that a newly init'd repository using this as its seed will get by default, max 50 characters; cannot be empty or absolute. Unlike the `config` command's own --folderadr, this one does NOT check whether the value would escape a repository once applied -- there is no repository yet at the point this file is written; that check happens later, in whichever command consumes this file as a seed (currently `init`).

### `--folderlog` *(optional, string)*

Relative path to the decision-log directory (ADR007V01) that a newly init'd repository using this as its seed will get by default, max 50 characters; cannot be empty or absolute, or the same as (or nested inside/around) --folderadr (config-folderadr-folderlog-overlap, checked even here). Omitting this flag keeps the currently stored value -- changing --folderadr alone does not move it; the 'decision-log' sibling of folderadr is only the default for a hand-edited file written before this field existed.

### `--migrationpattern` *(optional, string)*

Positional pattern for the legacy naming scheme, e.g. 'N00:04T04' (N##:##T##[V##:##][R##:##][P##:##]); the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `installconfig --seed` for that.

### `--template` *(optional, string)*

Default template content a newly init'd repository using this as its seed will get, max 10000 characters; a too-long value fails with config-template-too-long. The stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `installconfig --seed` for that.

### `--prefix` *(optional, string)*

ASCII letters only, max 5 characters; the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `installconfig --seed` for that.

### `--separator` *(optional, string)*

One of ('-', '_', '.').

### `--casetransform` *(optional, string)*

One of ('CamelCase', 'PascalCase', 'SnakeCase', 'KebabCase').

### `--statusnew` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to.

### `--statusacc` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to.

### `--statusrej` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to.

### `--statussup` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character. Also cannot contain '(', ')', '<!--', '-->', or ':' -- these four fields alone land inside the status cell's own parenthesized-date-then-marker grammar (ADR004V01's hidden canonical marker) and the Superseded row's own successor-reference suffix (which finds the FIRST ':' in the cell), so one of these characters could otherwise forge a date/marker the tool never wrote, or corrupt which successor a Superseded row points to.

### `--headerdisclaimer` *(optional, string)*

Header disclaimer text, max 100 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headertitlefile` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headerversion` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headerrevision` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headerscope` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headerdomain` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headertitlestatuscreated` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headertitlestatuschanged` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headertitlestatussuperseded` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headertablefields` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character. Also cannot contain '<!--' or '-->' -- these two build the header's table row, where an HTML comment is the migrated-header marker.

### `--headertablevalues` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character. Also cannot contain '<!--' or '-->' -- these two build the header's table row, where an HTML comment is the migrated-header marker.

### `--headermigrated` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--lenseq` *(optional, integer)*

Integer between 3 and 6 (inclusive); a non-integer value fails with field-not-an-integer.

### `--lenversion` *(optional, integer)*

Integer between 2 and 4 (inclusive); a non-integer value fails with field-not-an-integer.

### `--lenrevision` *(optional, integer)*

Integer between 0 and 3 (inclusive); a non-integer value fails with field-not-an-integer.

### `--disableplugins` *(optional, boolean)*

'true' or 'false'; anything else fails with field-not-a-boolean.

## Failure codes

| Code | Condition |
|---|---|
| `config-file-not-found` | --seed does not point to an existing file. |
| `language-not-supported` | --language is not one of SUPPORTED_LANGUAGES. |
| `field-not-an-integer` | An integer field's own value is not a valid integer. |
| `field-not-a-boolean` | --disableplugins is not 'true' or 'false'. |
| `io-error` | The write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |
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
# Read the current per-user default
adrpy installconfig

# Set one field for every future `init` on this machine
adrpy installconfig --separator _

# Seed every future `init` on this machine with a language pack
adrpy installconfig --language pt-br
```

---

This page mirrors the command's own `describe()` contract (the same JSON `adrpy help installconfig` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
