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

```mermaid
graph TD
    NAME["Name the file:<br/>{ISO date}--{classification}--{scope}--{slug}.md"] --> STRUCT{"Which classification<br/>did step 2 pick?"}
    STRUCT -->|"audit-finding<br/>or doc-drift"| LINE1["Add the structured line:<br/>Front | Severity | Resolution | Round"]
    STRUCT -->|deferred| LINE2["Add the structured line:<br/>Reopen-when: {condition}"]
    STRUCT -->|"anything else"| WRITE
    LINE1 --> WRITE
    LINE2 --> WRITE

    WRITE["Write the entry:<br/>one # heading = the one-line summary,<br/>free-form body below it"] --> REGEN["Run scripts/generate_decision_log_index.py<br/>to regenerate INDEX.md"]
    REGEN --> DONE(["Done -- never edit this entry again;<br/>a correction is a new retraction entry"])
```

## The rules that don't fit in the diagram

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
