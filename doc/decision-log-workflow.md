[← README](../README.md)

# Writing a decision-log entry

This page is the step-by-step workflow for adding an entry to
[`doc/decision-log/`](decision-log/INDEX.md): the lighter-weight sibling
of [`doc/adr/`](adr/), for events that are worth recording but are not an
architectural decision -- an audit finding, a retracted verdict, a
documentation-drift correction, a confirmed divergence from the reference
tool, a deferred item, an accepted trade-off, a checked-and-refuted
suspicion, or a one-off process exception. If you are looking for the
*full* classification vocabulary and the extra columns some entries carry
(`Front`/`Severity`/`Resolution`/`Round`), that lives in
[`doc/decision-log/INDEX.md`](decision-log/INDEX.md)'s own header --
this page does not repeat it, so the two never drift apart.

## Step 1: is this actually an ADR?

Ask one question before anything else: **does this change a choice among
design alternatives, with a lasting consequence for the architecture?**

- **Yes** -- this is not a decision-log entry. Open (or extend) an
  [ADR](adr/) instead, under this project's normal ADR-approval gate.
- **No** -- it's a finding, a correction, a retraction, a scoping note,
  or an accepted/deferred item. Continue below.

A clarification of what an *existing* ADR's own scope already covered is
still not a new architectural decision, even when it took real discussion
to confirm -- that's a `scope-note` entry, not a new ADR.

## Step 2: pick a classification

Classification is a closed vocabulary -- pick the one row below that
matches what actually happened. Full definitions (with edge cases) live
in [`doc/decision-log/INDEX.md`](decision-log/INDEX.md)'s own header;
this table is the quick lookup.

| Classification | Use it when... |
|---|---|
| `audit-finding` | A bug was found and fixed, or a review pass is closing a finding. |
| `retraction` | A prior verdict or claim (here or elsewhere) turned out to be wrong. |
| `doc-drift` | A durable doc (an ADR, this workflow page, ...) describes something that's no longer true. |
| `accepted-divergence` | Confirmed behavior differs from a reference, with no architecture change. |
| `scope-note` | Clarifies an existing decision's own boundary -- not a new decision. |
| `deferred` | Knowingly postponed, **with a concrete reopening trigger** you can name. No trigger you can name → it's `risk-accepted`, not this. |
| `risk-accepted` | A known gap left unfixed on purpose, with no reopening trigger. |
| `investigation` | A hypothesis was checked and did **not** hold (the narrative twin of a regression test for a fear that didn't materialize). |
| `process-exception` | A one-off, justified deviation from standing process -- scoped to this instance only. |

Add a new classification only when an entry genuinely fits none of these
-- a category invented for one entry is often a sign that entry is
actually an ADR in disguise.

## Step 3: write and register the entry

Once steps 1-2 are settled -- this genuinely belongs in the log, and you
know its classification -- run [`adrpy log`](commands/log.md)
([ADR003V01](adr/ADR003V01-decision-log-entries-separate-human-reviewed-judgment-from-tool-executed-mechanics-via-a-future-adrpy-log-command.md)).
It owns everything mechanical in one call: constructing the filename,
formatting the classification-specific structured line, writing the
entry, and regenerating `INDEX.md` -- and refuses outright
(`log-entry-already-exists`) instead of silently overwriting if the
exact same date/classification/scope/slug already exists. `--round` is
never a flag; `adrpy log` computes it itself (highest existing `Round`
across `audit-finding`/`doc-drift` entries, plus one) so it can never be
typed wrong or reused by mistake.

```bash
# Most classifications: no structured line
adrpy log --path . --classification scope-note --scope lock --slug clarify-timeout-behavior \
  --summary "Clarify what happens on timeout" --body "The full explanation goes here."

# audit-finding / doc-drift: --front/--severity/--resolution required together
adrpy log --path . --classification audit-finding --scope lock --slug retry-loop-off-by-one \
  --summary "Retry loop stopped one attempt short" --body "Details of the fix." \
  --front "test-adequacy audit" --severity Medium --resolution Direct

# deferred: --reopenwhen required instead
adrpy log --path . --classification deferred --scope security --slug posix-symlink-coverage \
  --summary "POSIX symlink-escape coverage deferred" --body "Windows-only today." \
  --reopenwhen "the test-adequacy audit front runs again"
```

Passing a structured-line flag for a classification that doesn't use it
(or omitting one it requires) is a `usage-error` -- see
[`doc/commands/log.md`](commands/log.md) for the full argument reference.

## Rules `adrpy log` doesn't enforce for you

- **No sequential numbering in the filename.** The slug (a few kebab-case
  words) is what guarantees uniqueness -- a sequential number would turn
  a gap, or an out-of-order entry, into something that misleadingly reads
  as its own finding.
- **One entry, one event, written once.** An entry is never edited to add
  a later correction -- that correction is a **new** entry, classification
  `retraction`, referencing the original entry's filename by name.
- **`scope`** reuses whatever module/command vocabulary the project
  already has (`lock`, `config`, `cli`, ...) -- never a fresh, one-off
  name invented for a single entry.
- **A cluster of entries around the same scope and concern is a signal,
  not yet a decision**, that there may be a real architectural gap
  underneath. If you notice one, propose opening an ADR that references
  the cluster as evidence, rather than continuing to add entries about
  what may be the same unresolved design question.
- **Cycles** -- a human-friendly name for a range of related entries,
  assigned only in hindsight once the span is over -- are recorded
  separately in [`doc/decision-log/CYCLES.md`](decision-log/CYCLES.md),
  never as a field on individual entries.
