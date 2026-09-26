<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Single-owner working copy without concurrency control, validating the whole repository before every lifecycle action|
|Version|01|
|Revision||
|Scope|core/consistency.py, core/fs.py|
|Domain|concurrency|
|Created|Proposed (2026-09-16) <!-- Proposed -->|
|Changed|Accepted (2026-09-16) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Single-owner working copy without concurrency control, validating the whole repository before every lifecycle action

## Deciders

* Deciders: Fernando Cerqueira (repo owner), in the architectural review that followed Round 42 (2026-09-24).

Technical Story: this ADR was first accepted on 2026-09-16 as "Repository lock covers the full critical section of every mutating command" (a whole-repository advisory lock with a pre-commit ownership recheck). The architectural review replaced that decision and, by a one-time exception the owner granted for that review only, this record was rewritten in place instead of superseded; the decision-log scope-note `2026-09-24--scope-note--architecture--architectural-review-single-owner-validate-before-acting.md` lists what was removed and why. The lock's history stays in git.

## Context and Problem Statement

adrpy is a per-invocation CLI that edits a folder of Markdown files inside a git working copy. From rounds 4 to 42 the project defended that folder against concurrent adrpy processes with a file-based advisory lock. Every round kept finding the same classes around it: a command that did not take the lock, data read before it was taken, a lease reclaimed from a slow holder, a read failure on the lock file itself, a partial write reported as "no write made", a folder that changed after the lock was placed in it. Round 42 found no tool-only safety or liveness violation left, and every remaining state-space finding needed a file edited outside the tool. The lock was protecting against a usage pattern (several adrpy processes on one working copy at once) that git already rules out for people, while the states that actually reach a repository (a hand edit, a merge of two branches, a multi-file write that stopped halfway) passed straight through it.

What should adrpy guarantee about concurrent use and about the state it finds on disk, so the guarantees are small enough to keep true and every broken state is reported instead of being tolerated or corrected command by command?

## Decision Drivers

* The lock was the single largest source of findings and code: 16 decision-log entries and 4 failure codes existed only because of it, and every command had to call it correctly.
* No advisory lock with a bounded lease and no heartbeat can give full mutual exclusion; the lock could only turn some races into a clean failure, never prevent them.
* Git already coordinates people: each person or agent works on their own clone or branch. Two adrpy processes on one working copy is a usage error, not a workload.
* The states that break a repository in practice come from outside a single adrpy call: hand edits, merges, a crash between the two writes of a multi-file command. A lock sees none of them; a validator sees all of them.
* The cost has to be measured, not assumed: validating the whole repository on every lifecycle action must stay cheap at a realistic, and at a large, repository size.

## Considered Options

* Keep the whole-repository advisory lock (the decision this ADR recorded until 2026-09-24).
* Optimistic concurrency control (compare a file's content or hash at write time and fail on a mismatch).
* No concurrency control: one owner per working copy, every lifecycle action validates the whole repository before acting, and a partial multi-file write is repaired by hand.

## Decision Outcome

Chosen option: "No concurrency control: one owner per working copy, validate before acting, manual repair", because it replaces a mechanism that could not keep its own promise with guarantees small enough to hold, and it turns every broken state, whatever made it, into a reported error with a repair hint.

The decision has five parts:

1. **One owner per working copy.** adrpy does no locking. One person or agent at a time runs adrpy (and `adrpy-skills`) on a given working copy; git coordinates people; when two commands do run at once, the last one to write a file wins. adrpy never calls git.
2. **What is still guaranteed, per file.** Every write is atomic: the complete content goes to a temp file next to the target, then an atomic move puts it in place, so a reader sees the old file or the new one. A new file is never created over an existing one (exclusive create: `file-already-exists`, `log-entry-already-exists`, `config-already-exists`), and the original stays intact. A temp file left by an interrupted write is swept later by a scanning command once it is older than 30 s. The retry budget for a transient permission error is per step: 5 attempts to prepare the temp file, 5 to commit it (`core/fs.py`).
3. **Validate before acting.** Every lifecycle action (`new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`) first validates the whole repository (`core/consistency.py`): headers, numbering, family and supersede invariants, and a complete scan. When anything is broken it stops with `repository-inconsistent` and `data.errors`, one entry per error with a repair hint, and writes nothing. `config` validates when it changes a guarded field, tolerating a file with no header so `migrate`'s own pattern can still be set. `explore`, `help`, `init`, `migrate` and `log` are exempt. `adrpy check` runs the same validation on its own and writes nothing. adrpy detects and reports; it does not prevent and does not repair.
4. **Manual repair after a partial multi-file write.** `supersede`, and `reject` of a successor, prepare both files first and commit them in a fixed order. When the second commit fails, the command reports `multi-file-write-partially-applied` with `data.applied`, `data.pending` and `data.repair` (the file and the exact header row to write by hand). There is no resume step; until the repair, every lifecycle action refuses the repository and `adrpy check` names the broken rule.
5. **Measured cost.** On a fixture of 5000 ADRs, `approve` including the full validation takes about 0.8 s; before the scan optimization of the same review (resolving only the root and link entries) it took about 1.4 s.

**Visibility plan for a lost update that ends in a valid state.** Most concurrent-use accidents leave a state the validator reports. One class does not: two commands on the same file that each write a valid result, for example a concurrent `approve` and `reject` of the same Proposed decision, where the last write wins and the repository is consistent. That case is made visible in three ways, none of them silent:

* The rule itself is documented where users and agents read it: the README's "One owner per working copy" section, `doc/architecture.md`'s "Single-owner model", the `adrpy-skills` README (`doc/skills/README.md`), and the shipped decision-log skill (`src/adrpy/resources/skills/decision-log/glue.md`), which tells an agent to run one `adrpy` command at a time.
* Every command reports what it wrote in its JSON result, so each caller sees its own outcome; the two callers of a lost update receive contradictory results.
* The decisions folder lives in git: `git diff` before a commit, and the history after it, show which write won. A repository whose history matters reviews ADR changes the same way it reviews code.

### Positive Consequences

* A broken repository is reported, with every error and a hint, whatever made it: a hand edit, a merge, parallel commands, or a partial write. Nothing is tolerated silently and nothing is "fixed" by guessing.
* The lock's code, its 4 failure codes, the resume path of `supersede` and the per-command recovery paths are gone; commands share one preparation and one validator instead of repeating guards.
* The guarantees left (atomic write per file, exclusive create, temp sweep, validate before acting) are small and each holds on its own.
* The validator also serves users directly (`adrpy check` in a pre-commit hook or CI), catching the merge of two branches that each created the same number.

### Negative Consequences

* Two commands run in parallel on one working copy can lose an update that ends in a valid state; only the visibility plan above covers it.
* A multi-file write that stops halfway needs a manual repair; the tool gives the exact row but does not apply it.
* Every lifecycle action pays for a full validation, about 0.8 s at 5000 ADRs.
* A repository adopted from AdrPlus 1.0.0 in a state AdrPlus allows but adrpy's invariants refuse must be repaired once, by hand, before lifecycle actions run on it.

## Pros and Cons of the Options

### Keep the whole-repository advisory lock

* Good, because it serializes adrpy processes that do run at once on one working copy.
* Bad, because a bounded lease without heartbeat cannot give full exclusion, only a clean failure for the losing side.
* Bad, because it sees none of the states that break a repository in practice (hand edits, merges, partial writes).
* Bad, because every command had to use it correctly, and the log shows that it repeatedly did not.

### Optimistic concurrency control

* Good, because it would detect a lost update at write time without a lock file.
* Bad, because it is a new mechanism on every write path (a conflict code, a content hash per file) for a usage pattern git already rules out.
* Bad, because, like the lock, it does nothing for hand edits, merges or partial writes.

### No concurrency control, validate before acting, manual repair (chosen)

* Good, because the guarantees are small enough to keep and every broken state is reported with a hint.
* Good, because the measured cost of validating on every action is small.
* Bad, because a lost update that ends in a valid state is only made visible, not prevented.

## Links

* `doc/decision-log/2026-09-24--scope-note--architecture--architectural-review-single-owner-validate-before-acting.md` -- the review that made this decision, the entries it removed and what it left out.
* README, "One owner per working copy"; `doc/architecture.md`, "Single-owner model"; `doc/lifecycle.md` -- the rule and the validator as users see them.
* `doc/adr/ADR006V01-decision-body-reads-and-writes-stream-chunk-by-chunk-instead-of-loading-whole-file-content-into-memory.md` -- the streaming writes that the atomic write per file carries.
