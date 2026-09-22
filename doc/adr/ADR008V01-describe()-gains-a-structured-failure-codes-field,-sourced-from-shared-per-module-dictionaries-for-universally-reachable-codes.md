<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|describe() gains a structured failure_codes field, sourced from shared per-module dictionaries for universally-reachable codes|
|Version|01|
|Revision||
|Scope|cli|
|Domain|tooling|
|Created|Proposed (2026-09-21) <!-- Proposed -->|
|Changed|Accepted (2026-09-21) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# describe() gains a structured failure_codes field, sourced from shared per-module dictionaries for universally-reachable codes

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided while closing the FailureCodes documentation-completeness gap ADR005V01's own registry left tracked (`tests/test_help.py::test_every_failure_code_is_documented_somewhere`, `xfail`).

Technical Story: closing that gap by hand-narrating the 62 still-undocumented codes as prose sentences inside each command's own `describe()` `description` text was rejected mid-discussion in favor of a structural fix -- most of the gap (~53 of 62 codes) is `core/config.py`'s schema-validation grammar and `core/header.py`'s header-parsing grammar, both reachable identically from nearly every command (`parse_repo_config` runs on every invocation's own config load; header parsing runs on every per-file command's own `read_target`), so narrating them as prose in 14 separate `describe()` bodies would mean writing (and maintaining) the same explanation over a dozen times.

## Context and Problem Statement

`doc/commands/INDEX.md` states a deliberate project position: there is no separate global failure-code index, because a code's meaning is only complete together with the specific write it guards. That position is correct for genuinely command-specific codes (`family-member-superseded` means something different in `supersede` than it would anywhere else), but it does not hold for the bulk of the currently-undocumented codes, which carry the *same* meaning everywhere they're reachable, because they come from the *same* shared validation step every command goes through at startup or at file-read time. Documenting those as free prose, once per command, either duplicates the same sentence a dozen times or -- the status quo -- gets skipped because doing it properly would bloat every command's own `description` into an even denser wall of text than it already is.

How should the remaining 62 failure codes get documented, given this project's stated no-global-index principle, its "JSON in, JSON out -- a fixed, documented set of failure codes per command" README commitment, and its allergy to prose duplication?

## Decision Drivers

* README's own stated design commitment: every command's own `describe()` response must be self-contained -- an agent calling `adrpy help <command>` must see everything that command can return, without a second fetch of anything else.
* `doc/commands/INDEX.md`'s existing, deliberate rejection of a global error-code index for context-dependent codes -- any fix must not silently walk that back for the codes it actually applies to.
* Of the 62 undocumented codes, ~40 are `core/config.py`'s own schema-validation grammar and ~13 are `core/header.py`'s own header-parsing grammar -- both reachable from virtually every command, with identical meaning regardless of which command surfaces them.
* `description`'s own free-prose text is already dense; the existing 75 already-documented codes have real narrative value (why the failure happens, what it means for the caller) that a mechanical flattening into terse one-liners would degrade, not improve.
* `tests/test_help.py`'s own completeness check currently works by substring-matching a `FailureCodes` string against free-form prose -- a fragile test shape for something that should be a structured completeness guarantee.

## Considered Options

* A dedicated markdown sub-page (`doc/failure-codes.md`) listing every code once, linked from each command's own doc page.
* Keep narrating every code as prose inside each command's own `description`, accepting the duplication for the ~53 shared codes.
* A new structured `failure_codes` field on every command's `describe()` response, populated from shared per-module dictionaries (`core/config.py`, `core/header.py`) for universally-reachable codes plus each command's own additions for the rest -- `description` untouched.

## Decision Outcome

Chosen option: **a new structured `failure_codes` field**, a list of `{"code": ..., "condition": ...}` objects (matching the shape `arguments` already uses, rather than a bare dict), covering all 137 `FailureCodes` a given command can actually return -- not just the previously-undocumented 62 -- so the field becomes the single, mechanically-checkable source of truth for "which codes can this command return," and the completeness test can check structured data instead of prose substrings.

The sub-page option was rejected outright: it would require an agent driving this tool headlessly to fetch a second document to learn about a failure mode its own `describe()` call didn't mention, the exact friction this project's "JSON in, JSON out" design principle exists to eliminate. It would also contradict `doc/commands/INDEX.md`'s own already-stated position for the codes that genuinely are context-specific.

The chosen shape does not actually reopen that position for those codes -- it recognizes that the ~53 shared-grammar codes never had command-specific meaning to preserve in the first place, and gives them exactly one source of truth (`core/config.py`'s and `core/header.py`'s own `SHARED_FAILURE_CODES` dictionaries, living next to the code that raises them, the same pattern `core/config.py`'s existing `_TOO_LONG_CODES` already established), merged into every relevant command's own `describe()` output rather than referenced from outside it. Every command's own JSON response stays self-contained; only the *authoring* location for the shared subset is centralized, not the *delivery*.

`description`'s existing prose is left untouched -- the 75 already-narrated codes keep their real explanations; `failure_codes` exists alongside prose, not instead of it, and no command's `description` text is required to mention a code just because `failure_codes` now does.

### Positive Consequences

* Closes `tests/test_help.py::test_every_failure_code_is_documented_somewhere`'s own tracked gap without duplicating the same explanation across a dozen `describe()` bodies.
* The completeness test moves from fragile prose substring-matching to checking real structured data -- a stronger guarantee, not just a different-shaped one.
* `doc/commands/*.md` (hand-mirrored from `describe()`) gains a clean, generated-looking table instead of more run-on prose.
* A future new failure code gets exactly one place its one-line condition needs to be written, for every command that can actually raise it.

### Negative Consequences

* A new field on a public JSON contract every consumer (human or agent) already depends on -- additive and backward-compatible, but still a real shape change worth this ADR existing at all.
* `failure_codes` and `description` can now say the same thing in two places (a full-prose explanation and a terser structured one) for the 75 already-documented codes -- accepted deliberately (`description` keeps its narrative depth; `failure_codes` is the mechanically-complete list), not an oversight.
* `doc/commands/*.md` stays hand-maintained (no generator script exists today) -- this ADR does not introduce one, so the new field's own table still needs the same manual-sync discipline every other part of that page already requires.

## Pros and Cons of the Options

### Dedicated markdown sub-page

* Good, because it is the least code: one new page, linked from every command's doc page.
* Good, because a human browsing docs gets one place to search every code at once.
* Bad, because it breaks self-containment for a headless agent -- `describe()` alone would no longer tell the whole story.
* Bad, because it silently reopens `doc/commands/INDEX.md`'s own stated rejection of a global index, for codes where that rejection still holds.

### Keep narrating every code as prose

* Good, because it changes nothing about the existing contract shape.
* Bad, because ~53 of the 62 missing codes would need the identical sentence written up to 14 times, with no mechanism to keep those copies in sync.
* Bad, because it is the status quo that produced the tracked gap in the first place -- writing 62 more prose sentences was already rejected as impractical before this ADR.

### Structured `failure_codes` field (chosen)

* Good, because every command's own `describe()` response stays fully self-contained.
* Good, because the ~53 shared-grammar codes get exactly one authored source, reused everywhere they're reachable.
* Good, because the completeness test becomes a structured-data check instead of a prose substring search.
* Bad, because it is a real shape change to a contract every consumer already depends on (mitigated: additive, existing fields unchanged).
* Bad, because `doc/commands/*.md` still needs hand-maintained syncing for the new field, same as every other part of that page today.

## Links

* Relates to: [ADR005V01](ADR005V01-failure-codes-and-shared-constants-gain-dedicated,-closed-registry-classes.md) -- this ADR closes the documentation-completeness gap ADR005V01's own registry left tracked via `xfail`, using the same "one shared source, not N duplicated copies" reasoning ADR005V01 itself established for failure codes' own wire values.
* Constrained by: `doc/commands/INDEX.md`'s own stated no-global-index position -- this decision narrows, rather than reverses, that position, scoping it to genuinely context-specific codes only.
