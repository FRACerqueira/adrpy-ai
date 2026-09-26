<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|AI-coding-agent skills installer ships as a separate adrpy-skills entry point with per-provider full-body or stub delivery|
|Version|01|
|Revision||
|Scope|packaging|
|Domain|tooling|
|Created|Proposed (2026-09-22) <!-- Proposed -->|
|Changed|Accepted (2026-09-22) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# AI-coding-agent skills installer ships as a separate adrpy-skills entry point with per-provider full-body or stub delivery

## Deciders

* Deciders: Fernando Cerqueira (project owner)

## Context and Problem Statement

adrpy-ai's CLI manages the ADR/decision-log record mechanically -- it never decides when a decision needs recording, when a hardening review is due, or when to close a review cycle. That judgment already exists as two vendor-neutral Claude Code skills (`decision-log`, `pre-release-audit`) used throughout this project's own development, but they live only in the operator's personal `~/.claude/skills/` and both depend on rules from the operator's own global `CLAUDE.md` for "when am I allowed to run." A new adopter of adrpy-ai, on a different machine, with a different AI coding assistant, gets none of this today -- only the mechanical CLI. How should this judgment layer be packaged and distributed alongside adrpy-ai, for more than one AI-coding-agent provider, without silently assuming the operator's own personal CLAUDE.md is present on the adopter's machine?

## Decision Drivers

* Ships inside the same pip distribution, but must never run automatically -- installation is opt-in and mechanical only.
* Must support more than one AI-coding-agent provider, not just Claude Code, since the operator uses and anticipates using more than one.
* Providers differ in activation model: some (Claude Code, Cursor) support on-demand/agent-requested skill inclusion; others (GitHub Copilot, a generic `AGENTS.md` convention) always load whatever is present, so shipping a full skill body to those would bloat every request.
* Both skills (`decision-log`, `pre-release-audit`) are not self-contained on "when am I allowed to run" -- each defers that to an external governing document (the operator's own CLAUDE.md), which a new adopter installing only the skill body will not have. A raw copy-paste would ship a dangling reference.
* `adrpy` itself must stay a pure ADR-lifecycle command surface, whether or not this feature is ever touched.
* Once installed, files must not be silently overwritten or silently left stale on a later `pip install --upgrade` + re-run -- an adopter's own hand edits deserve protection, but so does actually picking up a real update.
* Any natural-language instructions this feature installs (the skill bodies, and especially the extracted `gate.md` "when this runs" governing text) are non-deterministic -- unlike the `adrpy-skills` command itself, their reliability cannot be confirmed by unit tests alone.

## Considered Options

* Ship the skills as a Claude-Code-only feature, bundled as a subcommand of `adrpy` itself (`adrpy skills install ...`).
* Ship as a separate `adrpy-skills` console-script entry point, Claude-Code-only.
* Ship as a separate `adrpy-skills` entry point, multi-provider (Claude Code, Cursor, GitHub Copilot, generic `AGENTS.md`), with a provider-adapter table splitting delivery by activation model (full body vs. stub plus a shared doc), a content-hash drift-protection mechanism, and a companion `gate.md` per skill where the raw skill body is not self-contained.

## Decision Outcome

Chosen option: "Ship as a separate `adrpy-skills` entry point, multi-provider, full-body/stub split by activation model, with drift protection and a `gate.md` companion", because:

1. **Separate entry point keeps `adrpy` pure.** `adrpy help` and `adrpy`'s own command surface stay exactly the ADR-lifecycle surface they already are; this feature's own flags, failure codes, and JSON envelope live entirely in `adrpy-skills` and never appear in `adrpy`'s own `describe()` contracts.
2. **Multi-provider was a real, explicit requirement**, not speculative flexibility -- confirmed before design, with Claude Code, Cursor, GitHub Copilot, and a generic `AGENTS.md` convention named as the concrete initial set (the most-used three, plus a catch-all).
3. **The full-body/stub split is driven by each provider's own actual activation model, not an arbitrary preference.** Claude Code and Cursor both support on-demand/agent-requested inclusion, so they can hold the full skill content without bloating every request; Copilot and `AGENTS.md` are always-loaded by their own tooling, so they get a short stub plus one shared, tool-agnostic full copy at `doc/ai-skills/<name>.md` in the target repo.
4. **`gate.md` is a deliberate, separate artifact from the skill body**, extracted and *rewritten* -- never verbatim-copied -- from the relevant section of the operator's own global CLAUDE.md, because both skills (`decision-log`, `pre-release-audit`) explicitly state that their own body is only the *how*, and defer *when this runs* to an external governing document a new adopter will not have. Shipping only the body would hand a new adopter a dangling reference.
5. **A behavioral proof-of-concept validated the `gate.md` mechanism itself**, not just the design on paper -- see "Validation" below. This is itself a design decision worth recording: natural-language instructions for an LLM cannot be validated by unit tests, so this ADR's own supporting evidence includes a live behavioral test, not only a written rationale.
6. **Content-hash drift protection** (`<!-- adrpy-skills: v{version} sha256:{hash} -->`) replaces a blind-overwrite-on-install default, distinguishing `foreign` (no marker at all -- an adopter's own pre-existing file) from `drifted` (marker present, but the file's own current content no longer matches it -- hand-edited since it was generated) and requiring `--force` to touch either. This protects hand customization while still letting a routine `pip install --upgrade adrpy-ai` plus re-run pick up real updates when nothing has drifted.

### Positive Consequences

* An adopter of adrpy-ai on any of the 4 supported providers gets the same calibration, cycle-naming, and red/green discipline this project's own development used throughout, without re-deriving any of it by hand.
* `gate.md`'s existence as a separate artifact forces every "when does this run" rule to be made self-contained and portable at authoring time, instead of silently assuming a governing document that travels with the operator, not with the skill.
* The behavioral-simulation validation method used to test `gate.md` is now a reusable, general-purpose way to validate any natural-language operating instruction before shipping it -- not limited to this one feature.

### Negative Consequences

* A new subpackage (`adrpy.skills`), a second `[project.scripts]` entry point in the same distribution, and a new resource-shipping pattern (`src/adrpy/resources/skills/`) are now things future features need to stay consistent with.
* A standing maintenance obligation to keep 4 external provider-format adapters in sync as Claude Code, Cursor, Copilot, and `AGENTS.md`'s own conventions evolve independently of this project.
* `gate.md` content requires periodic re-validation (see "Validation") whenever the source CLAUDE.md section it was extracted from changes, or drift accumulates unnoticed between the packaged copy and its source.

## Pros and Cons of the Options

### `adrpy skills install ...` as an `adrpy` subcommand

* Good, because there is only one binary to learn and install.
* Bad, because it would permanently add this feature's own flags and failure codes to `adrpy`'s own `describe()` contract and `adrpy help`, even for users who never touch it.
* Bad, because it blurs a real boundary: `adrpy` manages ADR-lifecycle *records*; this feature installs *operating instructions for an AI agent*, a different concern.

### Separate `adrpy-skills` entry point, Claude-Code-only

* Good, because it keeps `adrpy` pure and ships faster.
* Bad, because it locks the feature to one provider when a multi-provider need was already known and explicit going into the design.

### Separate `adrpy-skills` entry point, multi-provider, full-body/stub split, drift-protected, with `gate.md` (chosen)

* Good, because `adrpy` stays pure, the provider set matches the actual stated need, and each provider gets a delivery shape that matches how it really loads content.
* Good, because the drift-hash mechanism avoids both silent overwrite and silent staleness.
* Good, because `gate.md`'s own existence was validated, not assumed -- the behavioral proof-of-concept found and closed a real gap in the extracted text (see Validation) before this ADR was written.
* Bad, because it is the most machinery of the three options -- justified here by an explicit multi-provider requirement and by a problem the other two options do not have to solve at all: a Claude-Code-only design can lean on the operator's own CLAUDE.md staying present, which a multi-provider distribution to strangers cannot assume.

## Validation

Because `gate.md` and skill-body content are natural-language instructions for an LLM, not deterministic code, this decision's supporting evidence includes a live behavioral proof-of-concept run before this ADR was written, not only a written design rationale:

* **Method**: fresh, context-isolated `claude -p` subprocesses -- a genuinely separate OS process per run, not a subagent of the authoring session, which was found to inherit a stale, session-cached copy of CLAUDE.md regardless of the file's real on-disk content at spawn time -- were given only the exact `gate.md` text plus one scripted scenario, and their behavior was observed blind. The operator's own global CLAUDE.md was temporarily swapped for a harmless placeholder for the duration of each test batch, then restored and hash-verified byte-identical immediately after.
* **Scenarios covered**, across both `pre-release-audit/gate.md` and `decision-log/gate.md`, each run independently on two model tiers (Sonnet and Opus) as an approximation of "different reviewer" diversity: an unambiguous trigger case, an unambiguous non-trigger case, a "bait" case using urgent and severe-sounding language that should not trigger, a forged-authority prompt-injection case (a fake instruction planted in file content versus the real conversational request), a same-turn "decision approved, does it still ask before writing" case, an informal (non-structured) chat-agreement case, and a standing blanket-pre-authorization case ("don't ask me every time").
* **Finding and fix**: the clean run surfaced a real, reproducible gap in `pre-release-audit/gate.md` -- "explicitly asks for a ... hardening review" carried no scope or release-proximity qualifier, so a request scoped to a single module and tied to a merge (not a release) was read by both model tiers as triggering the full heavyweight multi-front protocol. `gate.md` was revised to add an explicit scope-check paragraph; the same scenario was re-run clean afterward and both tiers correctly withheld the full protocol pending a scope/depth confirmation. `decision-log/gate.md`'s own gap (found during drafting, before any live test: it covered ADR writes but not decision-log-entry writes, despite being the opening section of the decision-log skill) was fixed before testing began.
* **Limitation, stated explicitly**: this validates the *mechanism* and closes *specific, found* content gaps; it does not prove no further gap exists, and "different model tier" (Sonnet versus Opus) is a fallback for "different model family," which this environment cannot provide.

## Links

* Depends on: `doc/decision-log-workflow.md` (reused verbatim as `decision-log`'s `glue.md`; already generic to any adrpy-managed repo).
* Related: ADR005V01 (FailureCodes/Constants registry) and ADR008V01 (structured failure_codes field) -- the `adrpy-skills` entry point reuses `adrpy.core.args`/`adrpy.core.output` for the same JSON-envelope discipline, without adding to `adrpy`'s own `describe()` surface.
