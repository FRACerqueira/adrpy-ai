<img src="../../src/adrpy/icon.png" width="64" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy config`

Reads or updates an existing repository's own `adr-config.adrplus`.

## Description

Reads or updates fields of an existing repository's adr-config.adrplus. With no field flags, reads the current config back (read-only, no write). `activeplugins` is never included in that read result or accepted as a field to update -- the plugin system is out of scope for now (see the `init` command's own note) -- so this is a subset of the raw file, not its full contents; do not round-trip it as `init --seed` input without adding `activeplugins` back. Omitted fields keep their current value; only the fields passed are updated. The result's own JSON shape differs by mode: a pure read's result has a `config` key (the current field values); a write's result never has that key at all, only `updated_fields` -- a generic wrapper that reads `data.config` unconditionally after any `config` call will KeyError on a write. --folderadr can only be changed while the OLD folder has no recognized decisions yet -- otherwise fails with folderadr-change-blocked-by-existing-decisions (data.existing_decisions names the count) rather than silently orphaning them at their old, still-real path; if that check itself can't be completed (a subdirectory couldn't be scanned), fails closed instead with folderadr-change-scan-incomplete rather than assuming nothing was there. --statusnew/--statusacc/--statusrej/--statussup/--separator can likewise only be changed while the repository has no recognized decisions yet (ADR004V01) -- otherwise fails with status-or-separator-change-blocked-by-existing-decisions (data.changed_fields names every guarded field this call touched, data.existing_decisions the count) rather than silently breaking recognition of those decisions; for --separator this is a PERMANENT block once any decision exists, with no migration path. Same scan-incomplete fail-closed shape as folderadr's own guard: status-or-separator-change-scan-incomplete. A write call may also fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed before the write could commit -- in both cases no write was made; a pure read (no field flags) never takes the lock. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry.

## Arguments

### `--path` *(required, string)*

Repository root directory.

### `--folderadr` *(optional, string)*

Relative path to the decisions folder, max 50 characters; cannot be empty, absolute, or escape the repository.

### `--migrationpattern` *(optional, string)*

Positional pattern for the legacy naming scheme, e.g. 'N00:04T04' (N##:##T##[V##:##][R##:##][P##:##]); the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that.

### `--template` *(optional, string)*

Default template content for a new decision's body; the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that.

### `--prefix` *(optional, string)*

ASCII letters only, max 5 characters; the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that.

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

Integer between 3 and 6 (inclusive).

### `--lenversion` *(optional, integer)*

Integer between 2 and 4 (inclusive).

### `--lenrevision` *(optional, integer)*

Integer between 0 and 3 (inclusive).

### `--disableplugins` *(optional, boolean)*

'true' or 'false'.

## Example

```bash
# Read the current config
adrpy config --path .

# Update one field
adrpy config --path . --lenrevision 2
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help config` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
