[← Command Reference](INDEX.md)

# `adrpy log`

Writes a decision-log entry -- the lighter-weight sibling of a formal ADR.

## Description

Writes a decision-log entry: the lighter-weight sibling of a formal ADR, for an event worth recording that is not itself an architectural decision (see doc/decision-log-workflow.md for when to use this instead of an ADR). Owns only the mechanical part of the record -- classification, scope, slug, summary, and body are all required arguments, since this command never decides what to log, only how to write it down once that's already been decided. May fail with log-classification-invalid if --classification is not one of the closed set named on that argument below, or log-slug-invalid if --slug is not valid kebab-case. May fail with repository-locked if the repository lock could not be acquired in time, or lock-lost if it was acquired but reclaimed before the write could commit -- in both cases no write was made. May also fail with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no write was made either way; retry. May also fail with log-entry-already-exists if an entry with the same date/classification/scope/slug already exists -- no write was made; this is a signal the new entry is a likely duplicate or should be a retraction of the existing one, not an accident to silently rename around. May also fail with log-index-regeneration-failed if the entry itself was written successfully but regenerating INDEX.md failed afterward (e.g. a permission error) -- `data.file` names the entry that was already committed to disk despite the overall failure.

## Arguments

### `--path` / `-p` *(required, string)*

Repository root directory.

### `--classification` / `-c` *(required, string)*

One of: audit-finding, retraction, doc-drift, accepted-divergence, scope-note, deferred, risk-accepted, investigation, process-exception.

### `--scope` / `-s` *(required, string)*

The module/command/concern this entry is about, reusing the project's own vocabulary. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character).

### `--slug` *(required, string)*

A few kebab-case words identifying this specific entry -- lowercase letters/digits only, single hyphens between words, no leading/trailing/double hyphens (log-slug-invalid). What actually guarantees the filename is unique.

### `--summary` *(required, string)*

One-line summary -- becomes the entry's own '#' heading. Cannot contain '|' or a line-break-like character (field-contains-forbidden-character).

### `--body` *(required, string)*

Free-form body text, written below the heading (and the structured line, if any).

### `--refdate` / `-r` *(optional, string)*

Reference date (YYYY-MM-DD) used as the entry's own filename date; defaults to today. Must not be in the future (refdate-invalid-format/refdate-in-future).

### `--front` *(optional, string)*

Required together with --severity/--resolution, only when --classification is audit-finding or doc-drift; usage-error otherwise. Which review angle found this.

### `--severity` *(optional, string)*

One of: Low, Medium, High. Required together with --front/--resolution for audit-finding/doc-drift.

### `--resolution` *(optional, string)*

One of: Direct, Escalated, Retraction. Required together with --front/--severity for audit-finding/doc-drift. --round is never a flag -- this command computes it automatically (highest existing Round across audit-finding/doc-drift entries, plus one), the same class of allocation as an ADR's own next_number, so it can never be typed wrong or reused by mistake.

### `--reopenwhen` *(optional, string)*

Required, and only valid, when --classification is deferred; usage-error otherwise. The concrete, checkable condition that reopens this deferred item.

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
