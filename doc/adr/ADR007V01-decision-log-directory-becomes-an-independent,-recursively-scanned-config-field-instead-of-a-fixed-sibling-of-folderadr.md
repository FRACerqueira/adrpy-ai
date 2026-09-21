<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|decision-log-directory-becomes-an-independent,-recursively-scanned-config-field-instead-of-a-fixed-sibling-of-folderadr|
|Version|01|
|Revision||
|Scope|decision-log|
|Domain|tooling|
|Created|Proposed (2026-09-21) <!-- Proposed -->|
|Changed|Accepted (2026-09-21) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Decision-log directory becomes an independent, recursively-scanned config field instead of a fixed sibling of folderadr

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided while closing round 28's systematic security-audit findings, in a follow-on architecture discussion about the decision-log directory's own location.

Technical Story: while investigating whether `folderadr` and the decision-log directory should become independently configurable (previously `decision_log_dir_for` derived the decision-log directory as `Path(folderadr).parent / "decision-log"`, a fixed sibling with no independent config field), it became clear this directly reopens a driver ADR003V01 already settled: ADR003V01 explicitly decided the decision-log directory's own location "cannot be added to the shared `adr-config.adrplus` schema" to preserve byte-compatible round-tripping with the reference AdrPlus tool. This ADR supersedes ADR003V01 to reverse that one driver -- deliberately accepting the fidelity loss -- while carrying forward everything else ADR003V01 decided (the `adrpy log` command's own mechanical-only scope, its fail-closed collision handling, and the project's "no wizard, ever" premise), none of which is affected by this change.

## Context and Problem Statement

`folderadr` and the decision-log directory are structurally unrelated concerns (one holds ADRs/decisions the tool's lifecycle commands manage end to end; the other holds lighter-weight audit/process entries the `adrpy log` command manages) that were coupled by convention alone: the decision-log directory was computed as `folderadr`'s own parent sibling, with no way to place it anywhere else. This coupling also produced a real asymmetry: `folderadr`'s own scan (`scan_decisions`) is recursive (`rglob`, covering subfolders), while the decision-log directory's own scan (`_existing_entries`) was not (`glob`, top-level only) -- never a problem while the two directories could never overlap by construction, but a real risk the moment either becomes independently configurable, since nothing would then stop the two from being pointed at the same directory, or one nested inside the other.

Should the decision-log directory become an independently configurable location, and if so, what does closing the resulting asymmetry and collision risk require?

## Decision Drivers

* Users increasingly want repository layouts where ADRs and process/audit entries live in genuinely different locations (different depth, different repository area, different retention/review policy) -- the previous fixed-sibling convention had no escape hatch for this.
* `folderadr`'s own scan is already recursive; making the decision-log directory recursive too (instead of leaving the asymmetry in place) is the only option that doesn't leave a real, freshly-relevant inconsistency unaddressed the moment both directories become independently placeable.
* Recursive scanning turns "the two directories can now point anywhere" into a real containment hazard: if `folderlog` (the new field) equals, or nests inside, `folderadr` (or vice versa), each directory's own recursive scan would start seeing the other's files -- the same class of adoption/misrecognition hazard ADR004V02 already closed for `--separator`, applied here to a directory-placement change instead of a naming-rule change.
* The project's own established discipline this session (ADR005V01, ADR006V01): when closing one gap reveals the underlying constraint is broader than first scoped, the broader shape gets its own ADR rather than a narrow patch bolted onto the original fix.
* Accepting the resulting deviation from the reference AdrPlus tool's own config schema is a deliberate, informed choice here (confirmed explicitly by the repo owner), not an oversight -- ADR002V01 already established the precedent that adrpy-ai's own config layer sometimes carries settings the reference tool has no equivalent for; this extends that precedent to `adr-config.adrplus` itself rather than confining it to the install-level config ADR002V01 introduced.

## Considered Options

* Leave the decision-log directory as a fixed sibling of `folderadr`, permanently -- reaffirm ADR003V01's own driver as-is; no new field, no containment risk, no fidelity loss.
* Add `folderlog` as a new field inside `adr-config.adrplus` itself, independently configurable, recursively scanned like `folderadr`, with a mutual containment guard between the two -- accepting the resulting loss of byte-compatible round-tripping with the reference tool's own config schema.
* Add `folderlog` to a NEW, adrpy-ai-only, per-repository config file, separate from `adr-config.adrplus` -- gets independence and recursion without touching the shared, reference-tool-compatible schema at all, preserving ADR003V01's original driver exactly as written.

## Decision Outcome

Chosen option: **add `folderlog` directly to `adr-config.adrplus`**, independently configurable and recursively scanned, with a mutual containment guard against `folderadr` -- because the repo owner explicitly confirmed accepting the fidelity trade-off, and a single shared config file is simpler for every command that already resolves repository config once, at the top of every invocation, than introducing a second, adrpy-ai-only config file alongside it. This formally **supersedes ADR003V01**'s own driver 4 and Decision Outcome item 3 ("any new... path setting... never merged into the shared `adr-config.adrplus` schema") -- everything else ADR003V01 decided (the `adrpy log` command's mechanical-only scope, its fail-closed collision handling on a same-day/scope/slug clash, and staying flag-driven with no interactive prompt) is unaffected and remains in force; this ADR does not reopen or relitigate any of it.

The decision has three parts, mirroring how `folderadr` itself is already governed:

1. **Independence and recursion.** `folderlog` becomes its own `adr-config.adrplus` field (own validation: relative path, non-empty, a length bound analogous to `FOLDERADR_MAX_LENGTH`), defaulting to the previous exact computed behavior (`{folderadr's own parent}/decision-log`) so a repository's `adr-config.adrplus` written before this field existed keeps working unchanged. The decision-log directory's own scan (`_existing_entries`, feeding `max_existing_round`/`next_round`/`regenerate_index`) is now recursive (`rglob`), matching `folderadr`'s own convention, and gained the same fail-closed-on-unreadable-subdirectory handling `scan_decisions` already has (round 8, ADR001) -- a class of risk the decision-log directory never had before because it was never recursive. Writing a new entry (`adrpy log`) still always targets `folderlog`'s own configured root directly, never a subfolder chosen by the tool -- "recursive" governs reading/indexing only, so a human can organize past entries into subfolders (by year, by cycle) without the tool losing track of them, without the tool itself ever deciding where to put a NEW entry.
2. **Mutual containment guard, in two layers.** `parse_repo_config` gained a new validation, comparing `folderadr` and `folderlog` by path COMPONENT (not string prefix, to avoid a false match like `"log"` vs `"log2"`) -- fails with `config-folderadr-folderlog-overlap` if the two resolve to the same relative path, or if either is an ancestor of the other, in either direction. This runs at config-parse time, before any filesystem access, the same layer `folderadr`'s own shape (relative, length-bounded) is already validated at -- **but this layer alone is necessary, not sufficient**: since it never touches the filesystem, it cannot see a Windows junction or symlink planted inside the repository tree that makes two configured strings sharing no path-component prefix at all (e.g. `"doc/adr"` and `"doc/other"`) alias the identical real directory (confirmed live, round 30, after this ADR's own first Accepted version: a hostile repository can ship both such a config and such a junction, silently defeating this layer). A second, real-filesystem-resolution guard (`core/security.py`'s `reject_aliased_repo_folders`, comparing `resolve_within`'s own resolved paths, not the configured strings) closes that gap -- called wherever `folderadr` and `folderlog` are both about to be used for real: `init`'s own folder-creation step, `config`'s own folderadr/folderlog change path, and `log`'s own read of `folderlog` for its normal work.
3. **Change guard.** Changing `folderlog` on an existing repository gets the same two-part safety `folderadr` already has for its own changes: refuses if the change would make existing decision-log entries invisible (mirroring `folderadr-change-blocked-by-existing-decisions`), and refuses if the new location already holds unrelated content that would be silently adopted under the new scan rules (mirroring the round-22/ADR004V02 adoption-hazard check).

**Implemented, not merely decided:** unlike this same session's ADR005V01 (whose registry refactor was Accepted with implementation explicitly postponed), this ADR's own implementation landed in the same working session it was Accepted in -- `core/config.py`, `core/decision_log.py`, `cli/config.py`, `cli/installconfig.py`, `cli/init.py`, `cli/log.py`, `default_repo_config.json`, `doc/commands/*.md`, and their tests. See the decision-log entry `2026-09-21--scope-note--decision-log--adr007-folderlog-independence-implemented.md` for the implementation's own closure record and independent verification evidence.

### Positive Consequences

* Repository layouts where ADRs and process/audit entries live in genuinely different locations are now possible, closing a real, requested gap in the previous fixed-sibling convention.
* The recursive-scan asymmetry between `folderadr` and the decision-log directory is closed in the same direction `folderadr` already established (recursive), rather than papered over by leaving `folderlog` non-independent.
* The containment guard closes the adoption/misrecognition hazard this change would otherwise have introduced, using the same "close the class, not the instance" reasoning ADR004V02 already applied to a structurally similar hazard.
* A concrete default (the previous exact computed sibling location) means no existing repository's `adr-config.adrplus` needed to change for this field to exist -- backward-compatible by construction, not by a migration step.

### Negative Consequences

* Formally reverses one of ADR003V01's own drivers -- a real, if narrow and explicitly confirmed, deviation from byte-compatible round-tripping with the reference AdrPlus tool's own config schema, the first time this project accepted that trade-off for the SHARED `adr-config.adrplus` schema itself (ADR002V01 only ever applied it to the separate, adrpy-ai-only install-level config).
* A real implementation cost (19 files touched in the end) landed for this, comparable in shape to what ADR005V01's own deferred registry refactor was estimated at.
* The decision-log directory's scan gaining recursion (and the fail-closed-on-unreadable-subdirectory handling that comes with it) added complexity to a module (`core/decision_log.py`) that was deliberately simple (no `warnings` machinery at all) specifically because it never needed to handle this class of risk before.

## Pros and Cons of the Options

### Leave the decision-log directory a fixed sibling (status quo)

* Good, because it costs nothing, introduces no containment risk, and keeps ADR003V01 fully intact.
* Bad, because it leaves a real, requested layout flexibility gap permanently unaddressed.

### `folderlog` inside `adr-config.adrplus` (chosen)

* Good, because it is simpler operationally -- one config file, already read once per command, gains one more field.
* Good, because the containment/change guards can be validated together with `folderadr` in the exact same `parse_repo_config` pass, no cross-file coordination needed.
* Bad, because it is a real, deliberate fidelity loss against the reference tool's own schema, the first time this project has accepted that trade-off for the shared schema itself rather than the separate install-level config.

### `folderlog` in a new, adrpy-ai-only per-repository config file

* Good, because it preserves ADR003V01's own driver exactly as written -- no fidelity loss at all, since the shared schema never changes.
* Bad, because it introduces a second config file every repository-scoped command would need to resolve and keep in sync with `adr-config.adrplus` (e.g. for the containment guard, which needs both directories' values at once) -- real, ongoing complexity for a trade-off the repo owner has already said is an acceptable one to avoid.

## Links

* Supersedes: [ADR003V01](ADR003V01-decision-log-entries-separate-human-reviewed-judgment-from-tool-executed-mechanics-via-a-future-adrpy-log-command.md) -- reverses driver 4 / Decision Outcome item 3 only; every other part of that decision remains in force.
* Related: [ADR004V02](ADR004V02-decision-status-recognition-uses-a-hidden-canonical-marker;-status-labels-and-the-filename-separator-both-gain-an-existing-decisions-guard.md) -- the same adoption-hazard reasoning this ADR's containment guard reuses, originally closed for `--separator`/`folderadr` changes.
* Related: [ADR005V01](ADR005V01-failure-codes-and-shared-constants-gain-dedicated,-closed-registry-classes.md) -- the same session, the same "recognize the constraint is broader than first scoped" reasoning; unlike this ADR, its own registry refactor remains deferred, not yet implemented.
* Closes: the decision-log entry recording this ADR's own implementation (`2026-09-21--scope-note--decision-log--adr007-folderlog-independence-implemented.md`) and the retitle half of `2026-09-21--scope-note--cli--supersede-title-flag-implemented.md`'s own linked deferred entry -- this file itself is the retitled replacement for the version that previously carried ADR003V01's own title verbatim (a `supersede --title` flag not existing yet at the time this ADR was first written).
* Revised (round 30): the schema-time containment guard (part 2 of the Decision Outcome above) was corrected from "closes the hazard" to "necessary, not sufficient" once a junction/symlink-based bypass of it was confirmed live -- see the round 30 decision-log entry closing that finding.
