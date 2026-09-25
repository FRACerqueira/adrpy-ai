<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Once a repository is adopted, a legacy-scheme name without a header is no longer a decision|
|Version|01|
|Revision||
|Scope|migrate|
|Domain|correctness|
|Created|Proposed (2026-09-25) <!-- Proposed -->|
|Changed|Accepted (2026-09-25) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Once a repository is adopted, a legacy-scheme name without a header is no longer a decision

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided during the Round 45 hardening round.

Technical Story: `migrate` exists to bring a repository that did not use adrpy (or AdrPlus) under the tool, once, at adoption -- AdrPlus's own Migration Guide calls it "a one-time operation". In practice it kept shaping the repository long after: Round 45's real-agent runs and the findings of Rounds 43-45 kept returning to `migrationpattern` and its consequences.

## Context and Problem Statement

`migrate` adds a header to each hand-written decision and never renames the file, in AdrPlus 1.0.0 and in adrpy alike: `0001-use-redis.md` stays `0001-use-redis.md`. Its number and title are read from the name through `migrationpattern`, so the pattern is needed for as long as the repository exists, and until now every file whose name it matches is a decision -- with or without a header. Three lasting effects followed:

* a note added months later whose name the pattern happens to match (`2024-01-15-meeting.md` under `N00:04T05`) becomes decision 2024, reported as `no-header`, and every lifecycle command refuses the repository until someone notices;
* the pattern cannot be changed once a migrated decision exists (the guard of `status-or-separator-change-blocked-by-existing-decisions`);
* every rule, scan and listing carries the second naming scheme.

adrpy must keep reading AdrPlus 1.0.0 repositories as they are, including files AdrPlus migrated under their legacy names, so reading legacy names cannot be dropped. The question is how much a legacy name keeps deciding after adoption.

How can `migrate` stay a one-time onboarding step, without legacy names deciding what is a decision for the rest of the repository's life?

## Decision Drivers

* `migrate` is an adoption step; after it, the repository should operate on decisions with headers only.
* No regression for AdrPlus 1.0.0 repositories: every file AdrPlus or adrpy migrated keeps being a decision.
* The hand-written-header path must keep working: when a repository already has decisions the tool created, `migrate` refuses (`already-tool-created-adrs-exist`) and check's warning tells the user to give each legacy file a header by hand.
* The adoption order must stay safe: before `migrate`, the files it will migrate must keep blocking the lifecycle commands, or a single `new` would create a tool-created decision and lock `migrate` out for good.
* The smallest change to already-tested behavior.

## Considered Options

* Keep as is: every name the pattern matches is a decision.
* A legacy name is a decision only when its header carries the `<!-- Migrated -->` marker.
* A legacy name is a decision only when it has a valid header, in every phase; without one it is a migrate candidate, reported as a warning.
* The same header rule, plus: while candidates exist and `migrate` can still run, the writing commands refuse.
* A phase rule: before adoption, a legacy name without a header is a decision with `no-header`, as before; once the repository is adopted, a legacy name without a header is not a decision, only a warning. Adoption ends when `migrate` can no longer run: when a decision has a valid header `migrate` did not write.
* `migrate` renames each file to an ADR name and then clears `migrationpattern`.

## Decision Outcome

Chosen option: "A phase rule", because it removes the lasting effect where it arises -- after adoption -- and leaves the adoption flow exactly as it was.

1. Before adoption, nothing changes: a legacy name without a header is a decision with `no-header`, check fails and every lifecycle command refuses until `migrate` runs.
2. The repository is adopted once any file in the decisions folder has a valid header `migrate` did not write -- created by the tool or AdrPlus, or copied by hand -- which is exactly when `migrate` stops running (`already-tool-created-adrs-exist`). Headers `migrate` wrote do not end the adoption: after a partial run, the files left keep blocking every lifecycle command until `migrate` finishes them, so no `new` can lock them out. Once adopted, a legacy name without a header is not a decision for any rule, count or listing; a command given it as `--file` refuses it (`filename-not-recognized`), and `check`, `explore` and every lifecycle command report it in a warning (give it a header by hand after renaming it to a free number -- its number may already be a decision's -- or move it out of the folder). Its number and title are not reserved: a new decision may take them, and the warning says so at that moment.
3. A legacy name with a valid header is a decision in both phases; one with a header that looks like this tool's but does not parse stays an `invalid-header` error in both.
4. `migrate` still finds every legacy name without a header, so a run after a partial one migrates what is left.
5. A read-only preview comes with it: `adrpy explore --path . --migrationpattern <pattern>` shows what a pattern would read from each name before `adrpy config --migrationpattern` writes it.

**Not done now: renaming during `migrate`.** Renaming would remove the second scheme for the repositories that go through it, but it breaks links to the old names from other documents, needs a rule for the `V` a name requires while a migrated header has a blank Version, and diverges from what AdrPlus 1.0.0 writes. It is deferred, not rejected. **Reopen when** a finding after this decision is again caused by a legacy-scheme name -- an `audit-finding` or `doc-drift` entry in the decision log whose cause is a legacy name: that would mean this rule was not enough, and renaming removes the cause itself.

### Positive Consequences

* After adoption, a file added later is never a decision because of its name alone: no repository is locked by a note.
* AdrPlus 1.0.0 repositories and hand-written headers keep working unchanged.
* `migrate` keeps its safe order: it cannot be skipped by accident before adoption.

### Negative Consequences

* What a legacy name means now depends on the whole repository (adopted or not), not on the file alone; every consumer has to ask one shared rule instead of the name.
* Before adoption, setting a wrong `migrationpattern` still makes check fail until it is cleared or `migrate` runs; the read-only preview and the `adrpy` skill's migrate rule are what keep that from happening.
* A repository with only migrated decisions and no decision the tool created is still adopting: a note added there whose name matches the pattern blocks until it is moved or migrated. The first `new` ends that phase.
* `migrationpattern` is still needed, and still guarded, for as long as migrated decisions keep their legacy names.

## Pros and Cons of the Options

### Keep as is

* Good, because nothing changes.
* Bad, because a matching name added at any time becomes a decision and blocks the repository.

### Only the `<!-- Migrated -->` marker counts

* Good, because the marker is on line 2 of every file AdrPlus or adrpy migrated.
* Bad, because a header written by hand (the documented path when `migrate` cannot run) has no marker, so those decisions would stop being recognized.

### The header rule in every phase

* Good, because a name alone never makes a decision, and setting a pattern never makes check fail.
* Bad, because before adoption check passes and `new` runs, creating a tool-created decision that locks `migrate` out for good.

### The header rule with writing commands refused

* Good, because it keeps both "a name alone never decides" and the adoption order.
* Bad, because check reports the repository as fine while `new` refuses the same state: two answers to one question, and one more rule to keep.

### The phase rule (chosen)

* Good, because it changes behavior only after adoption, where the problem is, and keeps the adoption order that validate-before-acting already enforces.
* Bad, because a pattern set by mistake before adoption still fails check until cleared.

The first draft of this rule ended the adoption at any valid header, migrated ones included. The Round 45 review showed that it let `new` run between two `migrate` runs and lock the files left out of `migrate` for good; the boundary was moved to where `migrate` stops running.

### Rename during `migrate`

* Good, because a migrated repository would have one naming scheme and no pattern left.
* Bad, because of broken links, the version rule it needs and the divergence from AdrPlus 1.0.0.

## Links

* Relates to [ADR004V02](ADR004V02-decision-status-recognition-uses-a-hidden-canonical-marker;-status-labels-and-the-filename-separator-both-gain-an-existing-decisions-guard.md) -- its guards protect recognition of existing decisions; the `migrationpattern` guard keeps counting only legacy decisions with a valid header.
* Relates to [ADR011V01](ADR011V01-adrpy-skills-ships-an-adrpy-skill-that-makes-an-ai-agent-use-the-cli-instead-of-editing-adr-files-by-hand.md) -- the shipped `adrpy` skill treats `migrate` as a one-time adoption step and previews a pattern before writing it.
