<img src="../../src/adrpy/icon.png" width="64" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy log`

Writes a decision-log entry -- the lighter-weight sibling of a formal ADR.

## Description

Writes a decision-log entry: the lighter-weight sibling of a formal ADR, for an event worth recording that is not itself an architectural decision (see doc/decision-log-workflow.md for when to use this instead of an ADR). Owns only the mechanical part of the record -- classification, scope, slug, summary, and body are all required arguments, since this command never decides what to log, only how to write it down once that's already been decided. Result shape: {"created": <path written>, "round": <int for audit-finding/doc-drift, else null>, "warnings": [...]}. May fail with log-classification-invalid if --classification is not one of the closed set named on that argument below, log-slug-invalid if --slug is not valid kebab-case, or log-scope-invalid if --scope is not valid kebab-case (scope becomes a literal segment of the entry's own filename, so '/', '\\', and an embedded '--' are rejected, not just cosmetically discouraged). May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with log-entry-already-exists (data.file: the bare filename) if an entry with the same date/classification/scope/slug already exists -- no write was made; this is a signal the new entry is a likely duplicate or should be a retraction of the existing one, not an accident to silently rename around. An existing file in the decision-log directory that doesn't match the expected naming shape refuses to be guessed past, but WHEN this surfaces depends on --classification: for audit-finding/doc-drift, the directory is scanned for Round allocation before any write, so this fails cleanly as log-directory-contains-unrecognized-file with nothing written; for every other classification, the directory is only scanned during index regeneration, AFTER the entry write already committed, so this surfaces as log-index-regeneration-failed instead (same as any other index-regeneration failure, e.g. a permission error) -- data.file (the full path, unlike log-entry-already-exists' bare filename above) names the entry that was already committed to disk despite the overall failure; the offending file's own name is in the detail text.

## Arguments

### `--path` / `-p` *(required, string)*

Repository root directory.

### `--classification` / `-c` *(required, string)*

One of: audit-finding, retraction, doc-drift, accepted-divergence, scope-note, deferred, risk-accepted, investigation, process-exception. audit-finding/doc-drift additionally require --front/--severity/--resolution (and accept optional --round); deferred additionally requires --reopenwhen; every other value accepts none of those four flags (usage-error if any are passed).

### `--scope` / `-s` *(required, string)*

The module/command/concern this entry is about, reusing the project's own vocabulary. Valid kebab-case only -- lowercase letters/digits, single hyphens, no '/', '\', or embedded '--' (log-scope-invalid); becomes a literal segment of the entry's own filename.

### `--slug` *(required, string)*

A few kebab-case words identifying this specific entry -- lowercase letters/digits only, single hyphens between words, no leading/trailing/double hyphens (log-slug-invalid). What actually guarantees the filename is unique.

### `--summary` *(required, string)*

One-line summary -- becomes the entry's own '#' heading. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank).

### `--body` *(required, string)*

Free-form body text, written below the heading (and the structured line, if any).

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD) used as the entry's own filename date; defaults to today. Must not be in the future (refdate-invalid-format/refdate-in-future).

### `--front` *(optional, string)*

Required together with --severity/--resolution, only when --classification is audit-finding or doc-drift; usage-error otherwise. Which review angle found this. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank).

### `--severity` *(optional, string)*

One of: Low, Medium, High (log-severity-invalid otherwise). Required together with --front/--resolution for audit-finding/doc-drift.

### `--resolution` *(optional, string)*

One of: Direct, Escalated, Retraction (log-resolution-invalid otherwise). Required together with --front/--severity for audit-finding/doc-drift.

### `--round` *(optional, integer)*

Only valid when --classification is audit-finding or doc-drift; usage-error otherwise. Optional even then: omit it to auto-assign the next round (highest existing Round across audit-finding/doc-drift entries, plus one) -- the safe default when starting a new round. Pass it explicitly to REUSE a round already in progress (the common case: a second finding in the same round), which auto-assignment can never do on its own. Must be a positive integer (log-round-invalid) not lower than the highest Round already recorded (log-round-too-low) -- Round never decreases. When omitted, the result's own `warnings` names the round that was auto-assigned, so an accidental new-round-instead-of-reuse is visible immediately instead of discovered later.

### `--reopenwhen` *(optional, string)*

Required, and only valid, when --classification is deferred; usage-error otherwise. The concrete, checkable condition that reopens this deferred item. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character), or be blank (field-is-blank).

## Example

```bash
# A plain entry, no structured line
adrpy log --path . --classification scope-note --scope lock --slug clarify-timeout-behavior --summary "Clarify what happens on timeout" --body "The lock wait ceiling and the abandon window are independent settings."

# audit-finding/doc-drift: --front/--severity/--resolution required, --round computed automatically
adrpy log --path . --classification audit-finding --scope lock --slug retry-loop-off-by-one --summary "Retry loop stopped one attempt short" --body "Details of the fix." --front "test-adequacy audit" --severity Medium --resolution Direct

# deferred: --reopenwhen required
adrpy log --path . --classification deferred --scope security --slug posix-symlink-coverage --summary "POSIX symlink-escape coverage deferred" --body "Windows-only today." --reopenwhen "the test-adequacy audit front runs again"
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help log` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
