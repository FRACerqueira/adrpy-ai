<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Failure codes and shared constants gain dedicated, closed registry classes|
|Version|01|
|Revision||
|Scope|core/errors.py|
|Domain|maintainability|
|Created|Proposed (2026-09-21) <!-- Proposed -->|
|Changed|Accepted (2026-09-21) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Failure codes and shared constants gain dedicated, closed registry classes

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided while closing a deferred decision-log item (doc/commands/INDEX.md's own "every failure code is documented" claim being checkably false).

Technical Story: closing decision-log entry `2026-09-21--deferred--cli--index-md-every-failure-code-documented-claim-is-false.md` required naming every command's own actual failure-code surface against its `describe()` text. A first, narrow pass (9 commands, ~20 codes) was fixed directly. A second, broader script cross-checking every `CommandError("...", ...)` literal across `src/adrpy/core/*.py` against every command's combined `describe()` text found 26 MORE codes never named anywhere -- 22 of them core/config.py's own field-by-field validation grammar (`config-prefix-invalid`, `config-lenseq-too-small`, `config-migrationpattern-invalid`, and so on), each one only discoverable today by reading the raw source of `parse_repo_config` directly, not by reading any `describe()` output. This is the second time in the same session a documentation-completeness gap of this shape has been found (the first closed only what a single audit round happened to touch); a third recurrence, on the current trajectory, is a "when," not an "if."

## Context and Problem Statement

Today, every failure code this project can return is a bare string literal, written once at its `raise CommandError("some-code", ...)` call site, with no single place that lists them all. The same is true of this project's shared constants and defaults (field-length limits like `STATUS_LABEL_MAX_LENGTH`, valid-value sets like `VALID_SEPARATORS`/`VALID_CASE_TRANSFORMS`, integer bounds like `_INT_FIELD_BOUNDS`) -- each lives as a module-level name in whichever file happens to use it first, sometimes duplicated (`config.py` and `installconfig.py` each define their own `_INT_FIELD_BOUNDS`). Keeping `describe()`'s own prose in sync with either list today depends entirely on whoever adds a new code or constant also remembering to document it by hand, with nothing that would fail loudly if they forget -- exactly the failure mode both rounds of today's gap-hunting exploited.

Is there a structural fix that makes "every code is documented" (and "every constant used is the single, canonical one") a property a test can actually verify, rather than a claim that has to be re-audited by hand every few months?

## Decision Drivers

* The same class of doc-drift (a failure code that exists in code but not in `describe()`) has now been found twice in one session, at increasing scope each time -- a purely reactive, read-the-source-and-patch-it-by-hand fix doesn't change the odds of a third recurrence.
* A single, closed registry of every failure code is a precondition for a PERMANENT automated test ("every code in the registry appears in at least one command's own `describe()` text") -- the only way to make doc/commands/INDEX.md's own claim durably true instead of true-until-the-next-untracked-addition.
* `_INT_FIELD_BOUNDS` is independently duplicated in `config.py` and `installconfig.py` today -- a real, already-existing drift risk (the two copies could silently diverge) that a shared constants module would also close as a side effect.
* This project already has an established, low-risk precedent for "introduce one shared module used everywhere instead of N local copies" (`core/security.py`, `core/io_retry.py`, `core/warnings.py` are all exactly this shape already) -- the pattern itself is not new to this codebase, only its application to failure codes and constants specifically is.

## Considered Options

* Do nothing differently; keep relying on periodic manual audits (like today's) to catch drift after the fact.
* One `FailureCodes`-shaped class PER MODULE (`config.py` gets its own, `lifecycle.py` gets its own, etc.), keeping codes close to where they're raised.
* One single, central `FailureCodes` class in `core/errors.py`, holding every failure code this project can return as a class attribute (e.g. `FailureCodes.CONFIG_PREFIX_INVALID = "config-prefix-invalid"`), imported everywhere a code is raised. A parallel, similarly centralized `Defaults`/`Constants`-shaped class for shared constants and default values (field-length limits, valid-value sets, integer bounds), replacing today's scattered/sometimes-duplicated module-level names.

## Decision Outcome

Chosen option: **a single, central `FailureCodes` class in `core/errors.py`**, plus an equivalent centralized treatment for shared constants/defaults -- because a per-module split would still leave no ONE place to point an automated completeness check at, which is the entire reason this decision exists. Centralizing also directly closes the already-confirmed `_INT_FIELD_BOUNDS` duplication between `config.py` and `installconfig.py` as a side effect, not a separate fix.

**Explicitly deferred, not implemented now:** the DECISION itself (this ADR) is Accepted -- what refactor to do, and why -- but the actual CODE CHANGE (touching an estimated 15-20 files across `src/adrpy/core/` and `src/adrpy/cli/`) is postponed as a pending item so the round-27/28 security-audit work already in progress can close out first. This is itself a "don't act automatically" decision in the sense the project's own guardrails call out -- the visibility plan for that is this ADR itself staying in the decision-log's own tracked history as Accepted-but-not-yet-implemented, plus the originating deferred decision-log item, until the refactor actually lands and a follow-up entry closes both.

### Positive Consequences

* A single, grep-able (and therefore lint-able/test-able) list of every failure code this project can return -- the precondition for a permanent, automated "every code is documented somewhere" test, closing the recurring doc-drift class this ADR exists to prevent, not just today's instance of it.
* Closes the already-confirmed `_INT_FIELD_BOUNDS` duplication between `config.py` and `installconfig.py` as a side effect of centralizing constants too.
* A new failure code or constant becomes harder to add "quietly" -- it has to be added to a shared, reviewable file, not just invented inline at whatever call site needed it that day.

### Negative Consequences

* A real, one-time refactor cost across an estimated 15-20 files -- every existing `raise CommandError("literal-code", ...)` call site needs updating to reference the new registry instead, a mechanical but non-trivial amount of change with real regression risk if done carelessly (a typo introduced while moving a string literal into a class attribute would silently change a failure code's own wire value).
* A single central class for ~150+ codes is a large file by this project's own usual standards -- a maintainer needs to search within it rather than finding a field's own codes co-located with the validation logic that raises them (already true today, in the other direction, for `_INELIGIBILITY_DETAILS`-style per-command dicts, which this decision does not immediately fold in -- see Considered Options; whether those also migrate into the central class, or stay local, is left to the implementation itself to decide).

## Pros and Cons of the Options

### Do nothing differently (status quo)

* Good, because it costs nothing now.
* Bad, because it does not change the odds of a third documentation-drift recurrence -- the same reactive, audit-then-patch cycle repeats, at whatever scope the next audit happens to reach.

### One class per module

* Good, because it keeps a module's own codes physically close to the logic that raises them, matching how `_INELIGIBILITY_DETAILS`-style dicts already work today.
* Bad, because it still leaves no single point an automated cross-check ("every code appears in some describe()") can be written against -- the actual problem this decision exists to solve.

### One central class (chosen, for FailureCodes; mirrored for Defaults/Constants)

* Good, because it is the only option that makes a permanent, automated completeness test possible.
* Good, because it closes the pre-existing `_INT_FIELD_BOUNDS` duplication as a side effect.
* Bad, because it is a real refactor across many files, with real (if mechanical, checkable) regression risk during the migration itself.
* Bad, because a very large single file is, on its own terms, a discoverability trade-off against the alternative -- accepted here because the trade-off it buys (a durably-closeable doc-drift class) is judged to matter more for this specific project, which has already spent real session time on exactly this recurring gap.

## Links

* Closes: decision-log `2026-09-21--deferred--cli--index-md-every-failure-code-documented-claim-is-false.md`
* Related: the same session's own broader security-audit rounds (`2026-09-21` decision-log entries, scope `security`), during which the second, larger wave of undocumented codes was found.
