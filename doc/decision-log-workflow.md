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

## Step 2: the full workflow

```mermaid
graph TD
    START(["Something worth recording<br/>happened"]) --> Q1{"Does it change a design<br/>choice with a lasting<br/>architectural consequence?"}
    Q1 -->|yes| ADR["Write an ADR instead<br/>(doc/adr/) -- stop here"]
    Q1 -->|no| Q2{"What kind of event is it?"}

    Q2 -->|"bug found & fixed,<br/>or a review closure claim"| AF["audit-finding"]
    Q2 -->|"a prior verdict or claim<br/>turned out wrong"| RT["retraction"]
    Q2 -->|"a durable doc describes<br/>something no longer true"| DD["doc-drift"]
    Q2 -->|"confirmed behavior differs<br/>from a reference, no<br/>architecture change"| ADIV["accepted-divergence"]
    Q2 -->|"clarifies an existing<br/>decision's own boundary"| SN["scope-note"]
    Q2 -->|"knowingly postponed, with<br/>a concrete reopening trigger"| DEF["deferred"]
    Q2 -->|"known gap left unfixed<br/>on purpose, no trigger"| RA["risk-accepted"]
    Q2 -->|"a hypothesis was checked<br/>and did NOT hold"| INV["investigation"]
    Q2 -->|"a one-off, justified<br/>process deviation"| PE["process-exception"]

    AF --> NAME
    RT --> NAME
    DD --> NAME
    ADIV --> NAME
    SN --> NAME
    DEF --> NAME
    RA --> NAME
    INV --> NAME
    PE --> NAME

    NAME["Name the file:<br/>{classification}--{ISO date}--{scope}--{slug}.md"] --> STRUCT{"Which classification?"}
    STRUCT -->|"audit-finding or doc-drift"| LINE1["Add the structured line:<br/>Front | Severity | Resolution | Round"]
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
