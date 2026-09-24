# Decision log (non-architectural)

This is the mechanics for a project's own "non-architectural decision
log" trigger rule. See "Writing anything this skill produces requires a
separate approval" above for the gate on *when* an entry is proposed --
this is the *how*, invoked once that gate is met.

## Why this exists

An architecture-decision record (ADR) exists to capture a choice among
genuinely different design alternatives, with a lasting consequence for
the architecture. Nothing else belongs inside one — not an audit
finding, not a retracted verdict, not a documentation-drift correction,
not a divergence that was confirmed but changes nothing about the
design. An accepted ADR is not a place to append this kind of note just
because it already has an open section that looks like a fit — once it
starts absorbing this content, the ADR stops being a decision record
and becomes a growing log —
indistinguishable from the actual audit trail, and eventually large
enough that nobody can tell, from the file alone, which of its many
lines is still the actual decision. This skill gives that content its
own place, small and disposable, so it never has a reason to live
inside an ADR again.

## Triage: does this belong in an ADR, or in this log?

One question, asked before proposing anything: **does this change a
choice among design alternatives, with a lasting consequence for the
architecture?**

- **Yes** → a new ADR (or a formal version/revision of an existing
  one), under the project's normal ADR-approval gate. This skill does
  not apply.
- **No** (it is a finding, a correction, a retraction, a scoping note,
  an accepted divergence with no design consequence) → propose an
  entry in this log, per the mechanics below.

Don't let "it feels architecture-adjacent" substitute for the test
above — a clarification of what an existing ADR's own scope already
covered is still not a new architectural decision, even when it took
real discussion to confirm it (that's a `scope-note` entry below, not
an ADR, and not an `accepted-divergence` either — nothing diverged from
an external reference, an existing decision's boundary was just made
explicit).

## Mechanics, once triage says "log, not ADR"

**Location: a sibling directory of the project's own decision-record
directory, never nested inside it (not even in a subfolder) — default
name `decision-log`.** Any directory a project's own tooling scans
recursively when looking for decision files will treat anything found
inside it as a candidate for one of its recognized naming schemes, and
a report that lists "every file found, including unrecognized ones"
would mix this log's entries into that same listing — the safest
exclusion is not being inside the scanned tree at all.

**If this location is configurable, it is one setting next to the
decision-record directory's own, and the two must never overlap** —
neither the same directory nor one nested inside the other, compared as
real paths, for the reason above.

**File naming**: `{classification}--{ISO date}--{scope}--{short-slug}.md`
— e.g. `audit-finding--2026-09-14--sequence-lock--stale-lock-cleanup.md`,
`doc-drift--2026-09-11--explore--folder-column.md`. No sequential
numbering: a sequential number is exactly the mechanism that turns a
gap, or an entry filed out of order, into something that reads as its
own finding — the same lesson ADR numbering itself already teaches.
The slug (a handful of kebab-case words describing the entry, not a
timestamp or counter) is what actually guarantees uniqueness: two
entries of the same classification, date, and scope are common — the
audit-closure trigger alone can produce several in one round — but two
entries about the *same specific thing* on the same day are not, and if
that ever happens it means the second one is a duplicate to merge or a
`retraction` of the first, not a new file.

**Classification is a closed vocabulary, fixed for the project — never
free prose.** A reasonable starting set:

- `audit-finding` — a bug found and fixed, or a closure claim from a
  review pass.
- `retraction` — a prior "correct, not a bug" verdict that turned out
  to be wrong, or a prior claim (in a log entry or elsewhere) that
  didn't hold under re-verification.
- `doc-drift` — an ADR or other durable doc describing something that
  stopped being true; the correction lives here, and the ADR itself is
  touched only if the architecture actually changed.
- `accepted-divergence` — a confirmed behavior that diverges from some
  reference (a prior system, a spec) without changing this project's
  own architecture.
- `scope-note` — a clarification of an existing decision's boundary,
  not a new decision.
- `deferred` — a fix or decision knowingly postponed. **Requires a
  named, concrete reopening condition** ("revisit when X happens" /
  "revisit before Y ships") — if no one can name that condition, it
  isn't deferred, it's accepted; use `risk-accepted` instead. This is
  the operational test between the two, not a matter of how the entry
  is worded. Carries its own structured second line, the same position
  `audit-finding`/`doc-drift` entries use for `Front`/`Severity`/
  `Resolution`/`Round`: `**Reopen-when:** {the condition, short and
  checkable}`. Free prose stays fine for the fuller "why deferred, not
  accepted" reasoning in the body — this field exists so the specific
  condition itself can be checked mechanically (by a person or a script
  re-scanning the log) without re-reading every `deferred` entry's own
  prose to remember what each one is waiting for.
- `risk-accepted` — a known internal limitation or weakness consciously
  left unfixed, with the reasoning, and no named condition for
  revisiting it — distinct from `accepted-divergence` (which is about
  differing from an external reference), this is about a gap in the
  project's own behavior.
- `investigation` — a suspicion or hypothesis that was checked and
  found **not to hold**, with no prior recorded verdict to retract — the
  narrative counterpart to a permanent regression test written for a
  hypothesis that didn't hold. A suspicion that *was* confirmed is not
  this: it's the bug it turned out to be, closed as `audit-finding` like
  any other.
- `process-exception` — a one-off, justified deviation from the
  project's own standing process or guardrail, scoped to this instance
  only, not a change to the guardrail itself.

Add a new classification only when an entry genuinely doesn't fit any
existing one — grep the existing set first. A category invented for
one single entry is a sign that entry might actually be an ADR in
disguise.

**Extending the vocabulary**: a project may need classifications this
list doesn't anticipate. Add them via a delimiter-separated list in the
project's own side config (never the shared/interop one) — e.g. a
single string value, pipe-delimited (`|`), holding only the
**additions**: `"spike|vendor-update|hotfix"`. This list only extends
the base vocabulary above, never replaces or removes from it — keeps
the closed-vocabulary discipline intact even as the project grows its
own categories, and a misconfigured/empty extension list degrades to
just the base set, never to an unconstrained free-text field.

**Scope** reuses whatever module/command/component vocabulary the
project already has — never a fresh, one-off name invented for the
entry. The same side config may hold a delimiter-separated extension
list for scopes that aren't literal command names (a cross-cutting
concern like security or observability, say), following the same
additive rule as the classification extension above.

**One entry, one event, written once.** An entry is not a section that
grows: no entry is ever edited to add a later correction or retraction
of *itself* — that correction is a **new** entry (classification
`retraction`, same scope as the original, referencing the original
entry's filename), never an edit in place. This is the constraint that
keeps this log structurally incapable of becoming a growing,
self-contradicting document the way an ADR can: the risk was never
wanting a place to write things down, it's a single file being edited
forever instead of a new one being written each time.

**Ask before writing, every time** — the same discipline as writing an
ADR, at the same gate: propose the entry (classification, scope,
one-paragraph content) and wait for confirmation before creating the
file. This applies even when the triage question above already
produced an obvious "yes, log this" — approving that something is
log-worthy is not the same as approving the write, exactly as with an
ADR. The bar to say yes is normally fast here, since there is no design
trade-off to weigh — but the ask itself is never skipped.

**Evaluate at the commit boundary, not from memory afterward.** The
failure mode this guards against was never forgetting the rule exists —
it was finishing a fix, moving straight to the next one, and only
remembering to log the first one much later, or never, until a
retrospective calibration pass caught the gap. Tie the check to the
same moment as the commit itself: immediately before committing a fix
(or as part of the same turn that commits it), run the triage question
above against what that specific commit actually did, and propose the
entry then and there if it qualifies — never deferred to "log the batch
at the end." A multi-commit stretch (an audit round, several fixes in a
row) gets this check once per commit, not once for the whole stretch
afterward; batching the *writes* once several entries are already
proposed and confirmed is fine, batching the *evaluation* itself is what
this line forbids. A calibration pass cross-checking commit history
against the log (see the `pre-release-audit` skill, if installed) stays
as a second, independent net — this discipline exists to make that net
rarely need to catch anything, not to replace it.

**Entry structure**: the first line of every entry is a single `#`
heading that doubles as its one-line summary — the only piece of an
entry's content the index (below) ever needs to read; everything else
in the entry is free-form.

**An `audit-finding` or `doc-drift` entry additionally carries a
structured second line**, immediately after the heading (before the
blank line and the free-form body): `**Front:** {which review angle
found this, may still mention the round narratively} | **Severity:**
{Low/Medium/High} | **Resolution:** {Direct/Escalated/Retraction} |
**Round:** {N}`. This exists specifically so a later calibration pass
(reconstructing each front's own convergence signal, per the
`pre-release-audit` skill, if installed) can read attribution,
severity, how the fix was reached, and which round it belongs to,
mechanically from every entry, instead of re-deriving them from free
prose or from whoever's memory of the round is still fresh. `Round` is
a single, project-wide, ever-increasing integer — never resets,
regardless of how much time passes between rounds or how the project's
own review-angle composition changes round to round. Keep it separate
from `Front`'s own prose even though both may mention the round:
`Front`'s mention is narrative color (e.g. "confirmation pass triggered
by round 9's X change"), `Round` is the one place a calibration pass —
or anyone else — reads the number from without parsing sentences. See
"Cycles" below for grouping a range of rounds under a human-friendly
name. `doc-drift` carries it too because it is the same shape of event
as `audit-finding` — a review angle found something wrong and it got
fixed — just scoped to a durable doc describing something that stopped
being true, rather than to the code directly; a front's own
convergence signal that silently excluded its `doc-drift` output would
under-count it. A finding with no dedicated front (surfaced by the
calibration pass itself, say, rather than a named review angle) still
gets the field, naming that explicitly (`Calibration (no dedicated
audit front -- found via X)`) rather than omitting it. Every other
classification (`retraction`, `accepted-divergence`, `scope-note`,
`deferred`, `risk-accepted`, `investigation`, `process-exception`)
doesn't carry this line — each of those is either not a front's own
finding-and-fix (a boundary clarification, a knowingly-deferred
decision, a checked-and-refuted hypothesis) or, for `retraction`, a
correction to a *prior* entry that keeps whatever Front/Severity/
Resolution that prior entry already had, not a new one of its own.

**`Resolution` is a checkable fact about how the fix was decided, not a
self-assessment of how clean the fix turned out.** `Direct` — the fix
followed an already-established pattern in the codebase with no design
choice to make. `Escalated` — the fix carried a real trade-off (more
than one defensible design, a breaking change, a cost) that was
presented as options and the project owner chose before it was
implemented; checkable against the actual conversation, not a vibe.
`Retraction` — the fix reverses a previously confirmed decision that
turned out not to hold (pair this with the `retraction` classification
when the earlier decision itself has its own entry to retract). `Direct`
does not mean risk-free — a fix that correctly followed an established
pattern can still have that pattern itself retracted later (that
becomes a `Retraction` entry when it happens, not a reason to relabel
the original `Direct` entry after the fact, per the "one entry, one
event" rule above).

## Cycles

A **cycle** groups a range of `Round` numbers under a human-friendly
name, for narrative/retrospective reference only. It is deliberately
**never a field on individual entries** — only `Round` lives there. A
sibling file, `CYCLES.md` (same directory as the entries — a project may
rename it, but never fold it into `INDEX.md`, which stays generated,
never hand-written), is the *only* place a cycle's name is ever
recorded, as a small table (round range, date range, name, and a
one-line justification).

This split resolves a real tension, not just a style preference: a
cycle's own dominant theme is only knowable once it's over
(retrospective), but an individual entry's fields must be stable the
moment it's written — nothing here is ever batch-edited later, same
discipline as "one entry, one event" above. Keeping `Cycle` off entries
entirely means naming one, or renaming one because a better name occurs
to someone later, never touches a single entry — only one row in one
small ledger.

**The naming rule**, once a cycle is worth naming:

1. Derive the name from the cycle's own dominant theme, grounded in the
   real content of its rounds (the `scope`/`Front` of its
   `audit-finding`/`doc-drift` entries, and any ADR born or touched
   during it) — never from a sequence number alone. State which entries
   support the name in `CYCLES.md`'s own notes column, so the name is
   checkable, not a guess.
2. Name the outcome, not the process. Test: could someone with zero
   context read the name and guess roughly what got safer/better?
   "Round 1-10" or "Initial audit push" fail this test (they describe
   that a process happened, not what changed). A name like "Concurrency
   & data-integrity hardening" passes.
3. Short, and immutable once written to `CYCLES.md`. A correction is a
   new note pointing at the old one, never an edit in place.
4. Named in hindsight, never planned in advance — a cycle's dominant
   theme isn't knowable until it's over.
5. Closed by the same signal `pre-release-audit` already uses to end an
   audit round of work, if that skill is installed: the project owner
   says it's done/paused for now, not a fixed round count or calendar
   cadence decided ahead of time. No second mechanism invented for
   this. If a new round is proposed after a long, ambiguous gap with no
   explicit close ever declared, ask whether it continues the current
   (still-open, unnamed) cycle or starts a new one — never assume
   either way.
6. Always proposed, never decided unilaterally by whoever's doing the
   writing — same "ask before writing" gate as every other decision-log
   write. A cycle can stay open and unnamed indefinitely; naming isn't
   mandatory until someone wants to reference the whole span as one
   thing.

**Index**: maintain a flat, generated index (path, classification,
date, scope, the entry's own `#` heading as its summary, plus
Front/Severity/Resolution/Round for the entries that carry them), rebuilt
from the entries themselves — never hand-maintained prose. If the
project's own tooling already regenerates an index for its ADRs and that
same mechanism can be pointed at a second root directory, reuse it for
this log too; otherwise a second, equally trivial regeneration (this
log's entries never need anything the ADR indexer's logic doesn't
already do) is the correct choice, not a reason to put this log's
entries where that indexer already looks. `CYCLES.md` (see "Cycles"
above) is a separate, small, hand-written table alongside the generated
index — the one deliberate exception to "never hand-maintained," since
a cycle's name is a human judgment call, not something derivable from
the entries alone.

## When a cluster of entries signals an actual ADR

If several log entries accumulate around the same scope and the same
underlying concern (three `audit-finding` entries all circling the same
predicate, say), that is a signal — not yet a decision — that there may
be a real architectural gap underneath. Surface it as a proposal to
open a new ADR that references the cluster as its evidence, instead of
silently continuing to add entries about what is actually the same
unresolved design question. Don't open the ADR unprompted; the trigger
for *that* is the project's own think-before-coding / evaluate-before-
adopting discipline, not this skill.

## Relationship to a pre-release audit

If the project runs a pre-release-audit-style review process (its own
practice, not something this skill defines), that process's own rule
about turning a class-closure claim into a checkable artifact is
satisfied **by an entry in this log**, not by an appended note in an
ADR: a "not a bug" verdict, a blast-radius enumeration, or a retraction
found in a later round all become `audit-finding`/`retraction` entries
here, named as verification targets for whichever pass runs next —
never folded back into whatever ADR happens to be nearby.
