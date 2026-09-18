<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Decision-log entries separate human-reviewed judgment from tool-executed mechanics via a future adrpy log command|
|Version|01|
|Revision||
|Scope|decision-log|
|Domain|tooling|
|Created|Proposed (2026-09-18)|
|Changed|Accepted (2026-09-18)|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Decision-log entries separate human-reviewed judgment from tool-executed mechanics via a future adrpy log command

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided directly through a design discussion evaluating whether `adrpy log` should exist as a new command.

Technical Story: a direct architecture discussion (not a pre-release-audit round) about closing the gap between how ADRs are managed (fully tool-owned, via `adrpy new`/`approve`/etc.) and how decision-log entries are managed today (entirely hand-authored, per the `doc/decision-log-workflow.md` process, with no tooling involved at all).

## Context and Problem Statement

Every decision-log entry today is written by hand, following a convention (filename pattern, closed classification vocabulary, a structured `Front`/`Severity`/`Resolution`/`Round` or `Reopen-when` line for some classifications, then a manual re-run of `scripts/generate_decision_log_index.py`) that exists only as documentation and an external AI skill -- nothing in `adrpy` itself enforces or executes any of it. This has two distinct, previously-observed failure modes: entries being forgotten entirely (the discipline of evaluating whether to log something *at the commit boundary* exists specifically because this has happened for real, more than once, on real projects), and mechanical drift when an entry *is* written by hand (a filename typo, a structured line formatted slightly differently from entry to entry, a forgotten index regeneration). ADRs do not have either problem, because the tool itself owns their mechanics end to end. Should `adrpy` gain an equivalent command for decision-log entries, and if so, what exactly should it own -- given the project's own "no wizard, ever" premise rules out simply automating the judgment calls (classification, wording) that currently require review?

## Decision Drivers

* The decision-log skill's own documented failure mode: forgetting to log a qualifying event has happened for real, which is why "evaluate at the commit boundary, not from memory afterward" is a standing rule, not a hypothetical concern.
* ADRs already separate judgment from mechanical execution cleanly: `adrpy new` creates a Proposed draft (mechanical, tool-owned); a human decides when to `adrpy approve` it (judgment, human-owned). Decision-log entries have no equivalent split today -- a human (or an AI assistant) does both the judgment *and* the mechanical writing by hand, in one step.
* `pyproject.toml`'s own project description and ADR002's own Decision Drivers both state "no wizard, JSON-only output" as a foundational, project-wide premise, not a per-command choice -- ruling out an interactive `adrpy log` that prompts for classification/content.
* The review gate that makes today's hand-authored process trustworthy ("propose the entry, wait for confirmation before writing," per the decision-log skill) is a property of the authoring workflow that happens *before* any file gets written -- it does not require living inside the CLI to keep working, and does not disappear just because the final write becomes a tool call instead of a hand-authored file.
* Decision-log filenames are deliberately **not** sequentially numbered (unlike ADR numbering) -- uniqueness is guaranteed only by a human-chosen slug. The moment file creation becomes mechanical and repeatable, a same-day/same-scope/same-slug collision becomes a real, not just theoretical, case that needs an explicit answer.
* Any new configurable vocabulary this needs (classification/scope extensions, the log directory's own location) cannot be added to the shared `adr-config.adrplus` schema -- the decision-log skill is explicit that this risks breaking byte-compatible round-tripping with the reference tool, and ADR002 already established the precedent of keeping tool-specific settings in adrpy-ai's own config layer instead.

## Considered Options

* Introduce `adrpy log`, scoped strictly to mechanical execution (naming, structured-line formatting, index regeneration, collision detection); judgment (triage, classification, wording) stays exactly where it is today, in the AI-assisted review workflow, unchanged. This ADR records the design; implementation is deferred.
* Introduce `adrpy log` as a fully interactive command that prompts for classification, scope, and content.
* Introduce `adrpy log` as a flag-driven command with no external review step -- callable directly by a human or agent, judgment and execution collapsed into one call.
* Keep decision-log entries permanently hand-authored; build no tooling for them at all.

## Decision Outcome

Chosen option: "Introduce `adrpy log`, scoped strictly to mechanical execution, judgment stays external, implementation deferred", because it is the only option that removes the mechanical-drift risk without asking the project to either violate its own "no wizard" premise (rules out the interactive option) or give up the review gate that makes an entry's classification trustworthy today (rules out the flag-only-no-review option) -- and because doing nothing leaves the documented forgetting failure mode permanently unaddressed.

The decision has three parts:

1. **Command scope.** `adrpy log` owns only mechanical execution: constructing the filename from `{ISO date}--{classification}--{scope}--{slug}` (this project's own established, date-first convention -- see `doc/decision-log/INDEX.md`'s own header and every existing entry), formatting the structured second line (`Front`/`Severity`/`Resolution`/`Round` for `audit-finding`/`doc-drift`, or `Reopen-when` for `deferred`) conditional on the classification passed in, writing the entry, and regenerating `INDEX.md` as part of the same operation. It never prompts, never supplies a default for a judgment field (classification, scope, slug, and the summary/body are all required arguments, forcing explicit intent instead of a wizard-style back-and-forth), and never decides *what* to log -- only how to write it down correctly once that's already been decided. Classification tokens and the structured-line field keys (`Front`/`Severity`/`Resolution`/`Round`/`Reopen-when`) stay in canonical English always, never following `--language` -- unlike ADR header labels (parsed positionally), these are matched by string across tools (the index generator, `pre-release-audit`'s calibration), the same category as JSON failure codes, which are never localized either.
2. **Collision handling.** If the computed filename already exists, `adrpy log` refuses outright with a distinct, structured failure code -- the same fail-closed shape `supersede` already uses for `file-already-exists` -- instead of silently overwriting or silently appending a disambiguator. This matches the decision-log skill's own stance: a same-day, same-scope, same-slug collision is a signal that the second entry is a duplicate to merge or a `retraction` of the first, not an accident to paper over automatically.
3. **Config surface.** Any new configurable vocabulary or path setting `adrpy log` needs lives in adrpy-ai's own tool-specific config layer, exactly as ADR002 already established for `installconfig` -- never merged into the shared `adr-config.adrplus` schema kept byte-compatible with the reference tool.

Implementation is explicitly **deferred** -- this ADR records the accepted design and the constraints it must satisfy; it authorizes no code yet.

### Positive Consequences

* Preserves the review discipline that makes today's decision-log entries trustworthy, without needing that discipline to live inside the CLI -- it already lives one layer up, in the authoring workflow, and stays there.
* Removes execution-level ambiguity (naming, structured-line formatting, index regeneration) the moment the command exists, giving decision-log entries the same mechanical guarantee ADRs already have.
* Gives decision-log entries an explicit, checkable collision boundary instead of an unstated hope that two slugs never coincide.
* Keeps `adrpy` internally consistent: every write command stays fully flag-driven, no interactive exception introduced.

### Negative Consequences

* Real, deferred scope of work once implementation is picked up: a new command, a new tool-specific config surface, and the same `describe()`/tests/`doc/commands/` rigor every other command already carries.
* Judgment (triage, classification, wording) remains entirely outside the tool's own guarantees -- a wrong classification is still possible, and still requires the same human/AI review this decision does not change or reduce.

## Pros and Cons of the Options

### Introduce `adrpy log`, mechanical execution only, judgment stays external, deferred

* Good, because it fixes exactly the class of risk that is actually mechanical, the same separation of concerns ADRs already have via `new` then `approve`.
* Good, because the review gate that makes today's process trustworthy is unaffected -- it was never a property of the CLI to begin with.
* Good, because it stays fully compatible with "no wizard, ever."
* Bad, because it is scope deferred, not solved today -- the forgetting failure mode this is meant to eventually close stays open until implementation happens.

### Fully interactive `adrpy log`

* Good, because an interactive prompt could in principle catch a malformed or inconsistent entry before it's written.
* Bad, because it directly violates "no wizard, ever" -- a foundational, project-wide premise, not a per-command choice.
* Bad, because it would be the only interactive corner of an otherwise fully non-interactive, scriptable/agent-driven CLI.

### Flag-driven `adrpy log`, no external review step

* Good, because it is the simplest to build -- no design split between judgment and execution to maintain.
* Bad, because it collapses judgment and mechanical execution into one ungated call, losing the "propose, then wait for confirmation" review step that exists specifically because classification is a judgment call, not a mechanical one.
* Bad, because nothing about *this* option is actually simpler than the chosen one to use correctly -- it just removes the safety net the chosen option keeps for free.

### No tooling at all

* Good, because it requires zero new code, config, or maintenance.
* Bad, because it leaves the documented forgetting failure mode, and the mechanical-drift risk of hand-authored entries, permanently unaddressed.
* Bad, because it leaves decision-log entries structurally behind ADRs forever, despite being explicitly designed as their lighter-weight sibling.

## Links

* [`doc/decision-log-workflow.md`](../decision-log-workflow.md) -- the current, fully human/AI-authored process this ADR's future `adrpy log` command would partially mechanize (naming, formatting, index regeneration only -- not classification).
