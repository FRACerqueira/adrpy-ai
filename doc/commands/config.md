<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy config`

Reads or updates an existing repository's own `adr-config.adrplus`.

## Description

Reads or updates fields of an existing repository's adr-config.adrplus. May fail with target-directory-not-found if --path does not point to an existing directory, or config-not-found if that directory has no adr-config.adrplus -- no write is attempted either way. With no field flags, reads the current config back (read-only, no write). `activeplugins` is never included in that read result or accepted as a field to update -- the plugin system is out of scope for now (see the `init` command's own note) -- so this is a subset of the raw file, not its full contents; do not round-trip it as `init --seed` input without adding `activeplugins` back. Omitted fields keep their current value; only the fields passed are updated. The result's own JSON shape differs by mode: a pure read's result has a `config` key (the current field values); a write's result never has that key at all, only `updated_fields` -- a generic wrapper that reads `data.config` unconditionally after any `config` call will KeyError on a write. --folderadr can only be changed while the OLD folder has no recognized decisions yet -- otherwise fails with folderadr-change-blocked-by-existing-decisions (data.existing_decisions names the count) rather than silently orphaning them at their old, still-real path; if that check itself can't be completed (a subdirectory couldn't be scanned), fails closed instead with folderadr-change-scan-incomplete rather than assuming nothing was there. The NEW folder is checked too: if it already exists and holds a file that would newly parse as a decision under the resulting config, fails with folderadr-change-would-adopt-unrelated-files (data.adopted_files lists the file paths) instead of silently absorbing it and corrupting next-number allocation -- the same scan-incomplete code above covers an unreadable subdirectory under the new folder too. Skipped entirely when the new folder does not exist yet. --statusnew/--statusacc/--statusrej/--statussup/--separator/--migrationpattern can likewise only be changed while doing so would not break recognition of an existing decision (ADR004V01/V02) -- otherwise fails with status-or-separator-change-blocked-by-existing-decisions (data.changed_fields names only the guarded field(s) actually blocking this call -- a field this call also touched, but whose own scope has no existing decisions at risk, is NOT listed there even though the call's atomic write still fails to apply it either; data.existing_decisions is the decision count actually at risk from those blocking field(s), not necessarily the repository's total). Status labels and --separator block if ANY recognized decision exists (current-scheme or legacy-scheme -- --separator's own recognition dependency is CURRENT-scheme-only, but a value that already appears inside a legacy filename can make that file newly match the current-scheme parser too, silently reclassifying it, so --separator cannot be scoped to current-scheme decisions the way --migrationpattern safely can); --migrationpattern blocks only if a LEGACY-scheme decision exists (parse_filename, the current-scheme parser, never reads migrationpattern, so no equivalent reclassification risk exists in that direction). This is a PERMANENT block once the decisions it actually protects exist, with no migration path -- for --statusnew/--statusacc/--statusrej/--statussup and --separator that means ANY recognized decision, any scheme (the ADR004V01 marker future-proofs RECOGNITION of files that already carry it against a later label change, but does not exempt THIS GUARD from refusing the config change itself -- the two are independent, and a marker-protected repository is blocked exactly the same as one with none); for --migrationpattern it means a LEGACY-scheme decision specifically. Same scan-incomplete fail-closed shape as folderadr's own guard: status-or-separator-change-scan-incomplete, whose own data.changed_fields DOES list every guarded field the call touched (not just the blocking ones) -- an unreadable subdirectory's own contents can't be ruled out for any guarded field, so this one fails closed unconditionally. --separator may also fail with separator-change-would-adopt-unrelated-files (data.adopted_files lists the file paths) if changing it would make a file NOT currently recognized as a decision (by either naming scheme) newly parse as one -- unlike --migrationpattern, which is deliberately allowed to newly recognize pre-existing legacy files (that is its own documented purpose), --separator has no such intentional-adoption use case, so any file it would newly sweep in is treated as an unintended side effect and blocked. This check only ever runs once the blocked-by-existing-decisions check above has already passed, so it only ever fires when zero existing decisions are at risk from this call -- not an edge case alongside a more common one where both could coexist, since those two outcomes are mutually exclusive by construction. A write call may also fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed before the write could commit -- in both cases no write was made; a pure read (no field flags) never takes the lock. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry.

## Arguments

### `--path` *(required, string)*

Repository root directory.

### `--folderadr` *(optional, string)*

Relative path to the decisions folder, max 50 characters; cannot be empty, absolute, or escape the repository.

### `--migrationpattern` *(optional, string)*

Positional pattern for the legacy naming scheme, e.g. 'N00:04T04' (N##:##T##[V##:##][R##:##][P##:##]); the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that.

### `--template` *(optional, string)*

Default template content for a new decision's body, max 10000 characters; a too-long value fails with config-template-too-long. The stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that.

### `--prefix` *(optional, string)*

ASCII letters only, max 5 characters; the stored value may be empty, but this flag can't set it to an empty string here (parse_flags rejects any empty optional value outright) -- use `init --seed` for that.

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
# Read the current config
adrpy config --path .

# Update one field
adrpy config --path . --lenrevision 2
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help config` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
