<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy installconfig`

Reads or updates the per-user, install-level default config.

## Description

Reads or updates the per-user install-level config (ADR002V01) -- used by `init` as its default seed when no --seed/--language is given, and by `migrate` as a migrationpattern fallback when a repository's own is empty. Unlike every other command, takes no --path: always operates on the one, fixed, per-user location this machine resolves to. With no field flags and no --seed, reads the current config back (read-only, no write); the result's `configured` key is false with no `config` key at all if the file doesn't exist yet -- the normal state for any installation that has never run this command, not an error -- or true with a `config` key otherwise. `updated_fields` is present as an empty list on every read too, same as `config`'s own bare-read shape -- a generic wrapper that reads `data.updated_fields` unconditionally works the same after any call, read or write. `activeplugins` is never included in that read result or accepted as a field to update -- same as the `config` command, the plugin system is out of scope for now -- but is still carried through unchanged from whatever base a write merges onto. Omitted fields keep their current value (or the built-in default's, on first write); only the fields passed are updated. A write call's result never has the `config`/`configured` keys. --seed replaces the file wholesale, same as `init --seed`, and reports every editable field in `updated_fields` since a full replace makes every one of them this call's own -- not a diff against whatever was there before. --language replaces the file wholesale too, with the built-in default's header/status labels and template swapped for that language's own -- same reporting rule as --seed applies to it.

## Arguments

### `--seed` *(optional, string)*

Path to a config JSON to replace the install-level config with wholesale, instead of merging individual field flags -- same semantics as `init --seed`. Fails with config-file-not-found if this path itself does not point to an existing file. The install-level config's schema is byte-compatible with a repository's own adr-config.adrplus, so this also covers importing one from a real installation of the reference tool's own template file directly, with no separate flag needed. Any field flag passed ALONGSIDE --seed raises usage-error -- pass one or the other -- same as `init`'s own incompatible flag combination (--seed with --language).

### `--language` *(optional, string)*

Built-in default language pack for header/status labels and the default template (one of ('en-us', 'pt-br', 'de-de', 'es-es', 'fr-fr', 'it-it', 'ja-jp', 'ko-kr', 'nl-be', 'ru-ru', 'zh-cn')), applied over the built-in default -- everything else (folderadr, separator, lenseq/lenversion/lenrevision, casetransform, migrationpattern) stays the built-in default's own value regardless of language. Replaces the file wholesale, same as --seed -- cannot be combined with --seed or with any individual field flag in the same call; usage-error either way, same rule --seed already applies to a co-passed field flag. Unlike `init --language`, this one is never blocked by an existing install-level config -- writing that config IS what this command is for.

### `--folderadr` *(optional, string)*

Relative path to the decisions folder that a newly init'd repository using this as its seed will get by default, max 50 characters; cannot be empty or absolute. Unlike the `config` command's own --folderadr, this one does NOT check whether the value would escape a repository once applied -- there is no repository yet at the point this file is written; that check happens later, in whichever command consumes this file as a seed (currently `init`).

### `--migrationpattern` *(optional, string)*

Positional pattern for the legacy naming scheme, e.g. 'N00:04T04' (N##:##T##[V##:##][R##:##][P##:##]); the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `installconfig --seed` for that.

### `--template` *(optional, string)*

Default template content a newly init'd repository using this as its seed will get; the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `installconfig --seed` for that.

### `--prefix` *(optional, string)*

ASCII letters only, max 5 characters; the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `installconfig --seed` for that.

### `--separator` *(optional, string)*

One of ('-', '_', '.').

### `--casetransform` *(optional, string)*

One of ('CamelCase', 'PascalCase', 'SnakeCase', 'KebabCase').

### `--statusnew` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--statusacc` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--statusrej` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--statussup` *(optional, string)*

Status label shown in the header table, max 25 characters; cannot be empty, contain '|', or contain a line-break-like character.

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

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

### `--headertablevalues` *(optional, string)*

Header row label, max 40 characters; cannot be empty, contain '|', or contain a line-break-like character.

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

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help installconfig` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
