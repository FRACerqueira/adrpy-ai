<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Failure responses carry a human-readable detail in the stdout JSON, with stderr kept as a copy outside the contract|
|Version|01|
|Revision||
|Scope|json-contract|
|Domain|cli|
|Created|Proposed (2026-09-23) <!-- Proposed -->|
|Changed|Accepted (2026-09-23) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Failure responses carry a human-readable detail in the stdout JSON, with stderr kept as a copy outside the contract

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided during the Round 38 pre-release audit's close.

Technical Story: the Round 38 usability front found that every failure's explanation (which flag was wrong, which file could not be read) is printed only to stderr, while stdout -- the one channel this project's contract describes -- carries only `code` (and sometimes `data`). A caller that captures stdout alone gets `usage-error` with no way to tell whether `--provider`, `--target` or `--skill` was the problem.

## Context and Problem Statement

Every `adrpy` and `adrpy-skills` response is one JSON object on stdout (`README.md`: "Every response is a single JSON object on stdout"; `doc/architecture.md`, "The JSON contract"). On failure, `core/output.py`'s `emit_failure`/`emit_usage_failure` write `{"success": false, "code": ..., "data"?, "warnings"?}` to stdout and the free-text `detail` to stderr. Nothing a user or an agent reads says the explanation is on stderr -- the only mention is an internal code comment (`core/errors.py`: "`detail` (stderr-only free text)"), and none of the bundled skills tells an agent to look there. Tool wrappers and `subprocess` callers commonly capture stdout only.

Where should a failure's human-readable explanation live, and what is stderr's status once it's decided?

## Decision Drivers

* The README's commitment: an agent must get everything it needs from the one JSON object on stdout.
* `code` and `data` are the stable, machine-decidable contract; the explanation text is free prose that may change between versions.
* A human running `adrpy ... | jq` in a terminal still wants to see the explanation while stdout goes into the pipe (the usual Unix split).
* No caller may break: stderr's current content is undocumented, but it exists.
* Only `core/output.py` writes to stderr today (two call sites), and only one test file reads it -- the change is small in either direction.

## Considered Options

* Keep as is: explanation on stderr only.
* Document stderr: say in README/architecture/help that stderr carries the explanation; the JSON unchanged.
* Two channels: add `detail` to the failure JSON on stdout, and keep writing the same text to stderr, documented as a copy for humans outside the contract.
* Stdout only: add `detail` to the JSON and stop writing to stderr at all.

## Decision Outcome

Chosen option: "Two channels", because it is the only option that gives a stdout-only caller the explanation without costing anything to a terminal user piping stdout elsewhere, and it breaks no caller.

1. Every failure JSON on stdout carries `detail`: the same human-readable explanation stderr already gets, whenever one exists. It is additive: no existing key changes, `code`/`data`/`warnings` keep their meaning.
2. `detail` is for humans, not for decisions. The documentation says so explicitly: decide on `code` and `data`; `detail`'s wording is not part of the contract and may change in any release.
3. stderr keeps receiving the same text, from the same call, so the two can never diverge. It is documented as a convenience copy for humans (visible in a terminal while stdout is piped), outside the contract -- nothing may depend on it.
4. The success response is unchanged.

### Positive Consequences

* A caller reading stdout only gets the full explanation of every failure.
* The contract stays in one place (stdout); stderr stops being an undocumented second source and becomes an explicitly non-contractual copy.
* No existing caller breaks: `detail` is a new key.

### Negative Consequences

* The explanation is emitted twice (stdout JSON and stderr) -- a small duplication by design.
* `detail` being free text invites parsing it; the documentation has to discourage that, and only `code`/`data` changes are ever treated as contract changes.
* Tests comparing a failure's JSON object byte-for-byte have to account for the new key.

## Pros and Cons of the Options

### Keep as is

* Good, because nothing changes.
* Bad, because a stdout-only caller never sees why a call failed, contradicting the README's own "everything on stdout" promise in practice.

### Document stderr

* Good, because it is documentation-only.
* Bad, because a stdout-only caller still gets nothing; it only moves the burden to every integrator.

### Two channels

* Good, because stdout-only callers get the explanation, and terminal users keep seeing it while stdout is piped.
* Good, because it is additive and both copies come from one call.
* Bad, because the text is emitted twice.

### Stdout only

* Good, because there is exactly one channel.
* Bad, because a human piping stdout (`| jq`) no longer sees the explanation on the terminal.
* Bad, because even this cannot guarantee an empty stderr: the Python interpreter itself still writes there on a failure before the entry point's own handler runs (an import error, for instance) -- only "the tool never writes to stderr" is guaranteed.

## Links

* Relates to [ADR008V01](ADR008V01-describe()-gains-a-structured-failure-codes-field,-sourced-from-shared-per-module-dictionaries-for-universally-reachable-codes.md) -- `failure_codes` documents what `code` values exist; this decision documents where each failure's explanation is delivered.
