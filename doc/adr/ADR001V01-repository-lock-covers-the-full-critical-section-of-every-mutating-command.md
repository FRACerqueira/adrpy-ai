<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Repository lock covers the full critical section of every mutating command|
|Version|01|
|Revision||
|Scope|core/lock.py|
|Domain|concurrency|
|Created|Proposed (2026-09-16) <!-- Proposed -->|
|Changed|Accepted (2026-09-16) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Repository lock covers the full critical section of every mutating command

## Deciders

* Deciders: Fernando Cerqueira (repo owner), confirmed after the round-4 pre-release audit (resilience, stability, and observability fronts, run in parallel and independently, all with empirically reproduced findings).

Technical Story: round 4 pre-release audit of `adrpy-ai`, stability front findings 1-3, resilience front findings 2-3, observability front finding 1, performance front's measured critical-section cost.

## Context and Problem Statement

`core/lock.py`'s repository lock was introduced in round 1 to stop two concurrent `new`/`supersede` calls from computing the same next-sequence-number. Round 4 found this lock does not actually provide mutual exclusion for the repository as a whole: 3 of 8 mutating commands never acquire it at all, and even the commands that do capture the data driving their write *before* entering the lock, so it protects only number allocation, never the write itself. Both gaps were empirically reproduced as real data loss / real file corruption, not just reasoned about. Given that no bounded-lease advisory lock without heartbeat can offer perfect exclusion, what should the lock's coverage, scope, and failure boundary be, so every command that mutates the repository is genuinely protected, without building a mechanism this tool's actual concurrency level doesn't justify?

## Decision Drivers

* Reproduced lost update: `approve` and `reject` running concurrently on the same file both report `success:true` with mutually exclusive final statuses — neither caller is told a conflict happened (round 4, stability Finding 1).
* Reproduced corruption: two concurrent `supersede` calls on the same predecessor produce two live successor files; the predecessor's own header references only one of them, leaving the other permanently orphaned (round 4, stability Finding 2).
* Measured cost: the full critical section (scan + decide + write) costs ~50-60ms at realistic team scale (200-300 decision files), ~270-290ms at 1000 files; uncontended lock acquire/release costs 6.58ms (round 4, performance front) — any fix has to be judged against this real, measured cost, not an assumed one.
* No advisory lock with a bounded lease and no heartbeat can offer perfect mutual exclusion against a process that is legitimately still working past the abandon window — the strategy needs an explicit, checkable boundary, not an open-ended promise.
* adrpy-ai is a per-invocation CLI driven by a handful of AI-agent/script callers, not a long-running, high-concurrency service — the fix must not introduce mechanism complexity the real expected concurrency doesn't justify.

## Considered Options

* Single whole-repository advisory lock, correctly scoped to the full critical section, with a pre-commit ownership recheck.
* Optimistic concurrency control (compare-and-swap on file content/hash at write time).
* Per-file or per-family fine-grained locking.
* External/distributed lock service.

## Decision Outcome

Chosen option: "Single whole-repository advisory lock, correctly scoped to the full critical section, with a pre-commit ownership recheck", because it closes every reproduced defect using the mechanism the project already has and already tests, at a cost the round-4 performance front's own measurements show is negligible at this tool's real scale, and it gives the lock's guarantee an explicit, checkable boundary instead of chasing a residual-race probability that bounded-lease locking can never fully eliminate.

The decision has three parts. It is a general invariant, not a fix for the two commands where it was reproduced — it applies to every command whose result depends on, or changes, shared repository state (`adr-config.adrplus` or the `folderadr` decisions folder):

1. **Universal coverage.** Every such command acquires `acquire_repo_lock` for its *entire* critical section. Compliant: `new`, `supersede`, `version`, `revise`, `approve`, `reject`, `undo`, `migrate`, `config`. Exempted, accepted risk: `init`, but only on its genuinely-fresh-bootstrap path — its `--seed` overwrite of an *already-existing* repository is live shared state, not bootstrap, and is fully compliant.

   **`init`'s exemption, and why:** unlike the other 8 commands — part of a steady-state lifecycle an AI-agent caller may legitimately invoke repeatedly and concurrently against a *live* repository — a genuinely fresh `init` is a one-time bootstrap operation on a path that, by definition, has no repository yet. Two processes racing to initialize the *same* fresh path is essentially always a coordination failure upstream of this tool, not a normal usage pattern this tool needs to defend against. The fix is also genuinely harder than the other commands' own: the lock's own storage location (inside the decisions folder) does not exist until `init` itself creates it, late in the same call the guard is trying to protect — a real chicken-and-egg `core.lock` does not solve today. Visibility plan (this repository's own standing rule: an accepted-risk decision needs one, not just a written record, since the silence it produces could otherwise pass for normal): `init`'s own `describe()` text states this limitation directly, in the JSON contract surface a caller actually reads before invoking the command (`src/adrpy/cli/init.py`).
2. **Freshness.** The data used to decide eligibility and to build a write's content is (re-)read *after* the lock is acquired, never captured before it. This closes the specific reproduced defect in `supersede` (predecessor header captured pre-lock, Finding 2) and applies identically to the equivalent pre-lock `load_target` calls already present in `version`/`revise`.
3. **Pre-commit ownership recheck — the explicit failure boundary.** Immediately before a command's final `atomic_write_text`, the lock file's token is re-read and compared against the token this process acquired. A mismatch aborts with a distinct lock-lost `CommandError` instead of writing. This does not, and structurally cannot, prevent every possible reclaim of a legitimately slow holder's lock — no bounded-lease lock without heartbeat/renewal can. What it guarantees is that the losing side of a reclaim always fails cleanly and visibly, instead of silently committing a write that collides with the new holder's.

`ABANDON_AFTER_SECONDS=30` is kept as-is. Measured critical-section cost sits 2-3 orders of magnitude below it at any realistic repository size (point above), so the residual risk is genuinely rare; closing it further with heartbeat/lease-renewal would add real mechanism complexity (another moving part with its own failure modes) to shrink a risk that point 3 already converts from "silent corruption" to "clean, explicit failure" — which is the correct, sufficient posture for a non-interactive CLI whose caller can simply retry on a structured error.

### Positive Consequences

* Closes both HIGH-severity, empirically reproduced defects (`approve`/`reject`/`undo` lost updates; `supersede`'s orphaned successor) using the existing mechanism — no new dependency, no new concurrency-control concept for the codebase to learn.
* Gives the lock's guarantee an explicit, statable boundary: mutual exclusion holds for any critical section completing within the abandon window; anything exceeding it fails cleanly, never silently.
* Negligible measured performance cost at this tool's real scale (round-4 performance front).
* One uniform pattern across every mutating command — a future command follows the same three rules by construction, instead of needing its own ad hoc concurrency reasoning.

### Negative Consequences

* Real, multi-file change: touches `approve.py`, `reject.py`, `undo.py`, `migrate.py`, `config.py` (add the lock), plus `supersede.py`/`version.py`/`revise.py` (move the freshness-critical read inside the lock), plus a shared pre-commit-recheck helper (`RepoLock.verify_still_held`).
* Does not eliminate the residual race window on a pathologically slow filesystem (a critical section genuinely exceeding 30s) — it only guarantees that case fails safely instead of preventing it outright. This is an accepted, documented limit, not something later work should treat as still open.

## Pros and Cons of the Options

### Single whole-repository lock, correctly scoped, with pre-commit recheck

* Good, because it reuses a mechanism the project already has, already understands, and already tests, rather than adding a new one.
* Good, because the round-4 performance front's own measurements show the cost is negligible at this tool's real scale (tens of ms).
* Good, because the pre-commit recheck gives an explicit, checkable failure boundary instead of an open-ended promise the lock structurally cannot keep.
* Bad, because it still cannot fully prevent a reclaim mid-critical-section on a pathologically slow filesystem — only convert it from silent corruption into a clean, visible failure.

### Optimistic concurrency control (compare-and-swap on content/hash)

* Good, because it would also protect against any future gap in lock coverage, not only the ones already found.
* Bad, because it is a new mechanism this project doesn't have today (content/hash comparison at write time, a new conflict error code, new tests) to solve a problem the corrected lock already solves at this tool's real, measured concurrency level.
* Bad, because it doesn't remove the need to fix the lock's own coverage gaps either (Finding 1) — it would be additive complexity on top of the required fix, not a replacement for it.

### Per-file or per-family fine-grained locking

* Good, because it would serialize less work in a hypothetically much larger or busier repository than this tool's real usage pattern.
* Bad, because the invariants this tool actually protects (the next sequence number, a family's sibling state) are inherently cross-file — a lock scoped to one file cannot protect either one.
* Bad, because holding multiple simultaneous fine-grained locks (e.g. two family members touched by the same operation) introduces lock-ordering/deadlock risk with no corresponding benefit at this tool's real scale.

### External/distributed lock service

* Good, because it would work across machines or mount points that a local file-based lock cannot reach.
* Bad, because it is a new external dependency and operational surface for what is otherwise a local, per-invocation CLI tool operating on a folder of Markdown files.

## Links

* Round 4 pre-release audit (2026-09-16): stability front Finding 1 (`approve`/`reject`/`undo` hold no lock, reproduced), Finding 2 (stale pre-lock header defeats `supersede`'s predecessor-mutation protection, reproduced), Finding 3 (lock reclaimable mid-critical-section, mechanism verified); resilience front Finding 2 (a malformed lock file left by a crash is never reclaimed, reproduced) and Finding 3 (fixed lease with no renewal, reasoned); observability front Finding 1 (`_unlink_with_retry`'s return value is ignored by both call sites that need it, reproduced); performance front's measured critical-section and lock-overhead numbers.
* `doc/decision-log/` — the sibling mechanism this repository uses for audit findings, doc-drift corrections, and other non-architectural events, so this record stays a decision, not a growing log. In particular: the second corroboration pass that confirmed and fixed `migrate`/`config`'s own lock gaps (`2026-09-16--audit-finding--lock--second-corroboration-pass-confirms-migrate-and-config-lock-gaps.md`), and round 5's own re-run findings against this same invariant (`audit-finding`/`doc-drift`/`investigation`/`scope-note` entries dated 2026-09-16) — see `doc/decision-log/INDEX.md` for the full, current list. This ADR itself is deliberately recorded here, as an ADR, because it is a from-scratch architectural decision about `adrpy-ai`'s own concurrency model, not a divergence from the original tool's behavior.
