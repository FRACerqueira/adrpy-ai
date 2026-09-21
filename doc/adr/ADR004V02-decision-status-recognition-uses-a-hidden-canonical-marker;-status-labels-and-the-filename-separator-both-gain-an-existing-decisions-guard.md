<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Decision status recognition uses a hidden canonical marker; status labels and the filename separator both gain an existing-decisions guard|
|Version|02|
|Revision||
|Scope|header|
|Domain|correctness|
|Created|Proposed (2026-09-20) <!-- Proposed -->|
|Changed|Accepted (2026-09-21) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Decision status recognition uses a hidden canonical marker; status labels and the filename separator both gain an existing-decisions guard

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided directly through a design discussion that started from a globalization/onboarding question and surfaced a live parsing bug along the way, then widened in scope when the same question ("what else has this shape?") was asked deliberately before implementation started.

Technical Story: a direct architecture discussion (not a pre-release-audit round) that began with "how does a first-time user discover and set the repository's language/config," moved into "what happens if `--language`/`config` changes a status label after decisions already exist," and was confirmed live: changing `config --statusnew` on a repository with an existing decision made that decision `is_valid: false` -- the tool stopped recognizing it entirely. Before implementation, the same question was asked of every other config field: does anything else determine whether an existing decision is *recognized at all* by comparing against the repository's *current* config? One more field was found and confirmed live the same way: `separator`.

V02 update (2026-09-21): a post-implementation stability audit of the marker/guard code (scoped specifically to this ADR's own area, not a periodic sweep) found that V01's own dismissal of `migrationpattern` was wrong, and traced its root cause to a second, related gap in the guard's own design. Both are corrected below; the marker mechanism itself (V01's core contribution) is unchanged.

## Context and Problem Statement

Three independent config fields determine whether an already-written decision is recognized at all, by comparing something already fixed in the file against the repository's **current** config value for that field, re-read fresh on every parse:

1. **Status labels** (`statusnew`/`statusacc`/`statusrej`/`statussup`): `core/header.py`'s `_parse_status_cell` matches each status row's cell text against these four values (`label_to_status`, rebuilt fresh every parse) to recognize Proposed/Accepted/Rejected/Superseded.
2. **`separator`**: `core/naming.py`'s `parse_filename` locates the boundary between the number/version/revision segment and the title via `name.find(config.separator)` -- confirmed live: changing `config --separator` from `-` to `_` on a repository with one existing decision made `explore` report that file with `scheme: null, number: 0, title: null` -- the filename stops being recognized at all (the header content itself stays readable; only the file's identity, derived from its name, is lost).
3. **`migrationpattern`** (V02): `core/naming.py`'s `parse_legacy_filename` re-derives a LEGACY-scheme file's number/version/revision/prefix by POSITION and LENGTH from `parse_migration_pattern(config.migrationpattern)`, read fresh on every call -- nothing pinning a legacy file's own identity is stored in the file itself, exactly the same shape of dependency as `separator`, just for the other naming scheme. V01 dismissed this field with an argument that only addressed WRITE dependency ("not a value this tool's own writes depend on staying stable") and never checked its READ/recognition dependency, which `parse_legacy_filename`'s own source shows directly. Confirmed live: a `migrationpattern` change that shrinks the parsed field lengths makes an existing legacy file stop being recognized entirely (same failure shape as `separator`); a change that keeps the file's raw length "fitting" the new pattern but shifts field positions is worse -- the file is silently RE-recognized under a different number/version/revision, with zero warning, risking a next-number collision or a silently-dropped family member.

Both status labels and `separator` are byte-for-byte replicas of the real AdrPlus (C#) tool's own design (confirmed directly in its source: status matching in `AdrPlusRepoConfig.StatusMapping`/`Helper.ParseStatusLine`, `C:\Sources\AdrPlus\src\AdrPlus\Domain\AdrPlusRepoConfig.cs:179-186` and `Core\Helper.cs:253-283`; separator matching in `AdrService.cs:575`, `supersedeParts[0].IndexOf(separator, ...)`) -- neither is a defect introduced by this port; AdrPlus has the identical fragility in both cases. `migrationpattern`/the legacy scheme is adrpy-ai's own accommodation for pre-existing hand-written files (see ADR002V01); AdrPlus has no equivalent concept at all, so this third field has no AdrPlus-side counterpart to stay compatible with.

Every other config field was checked the same way before settling scope, to close the class rather than the instances already found: `prefix` (confirmed live: safe, the filename regex captures any prefix without comparing it to config), `casetransform` (safe, title is extracted as literal text, never re-cased for comparison), `lenseq`/`lenversion`/`lenrevision` (safe by pre-existing, deliberate design -- `core/naming.py`'s own docstring already states digit runs are matched at variable length for exactly this reason), the 11 header row labels plus `headerdisclaimer` (safe, positional only, never parsed), and `template` (safe, never compared back, only used as initial content for a new decision).

**A second, related gap found during the same audit**: V01's guard treated `separator` as blocked by "any recognized decision exists," regardless of which naming scheme that decision uses -- but `parse_filename` (current scheme) never reads `migrationpattern`, and `parse_legacy_filename` (legacy scheme) never reads `separator`; each guarded field only actually affects ONE scheme's recognition. A blanket "any decision" check is imprecise both ways: it already over-blocked `separator` changes on legacy-only repositories (harmless, since separator has no bearing there), and naively adding `migrationpattern` to the same flat blanket check would have introduced the mirror problem (blocking a harmless `migrationpattern` change on a current-scheme-only repository). Status labels are the one field group where "any decision, any scheme" is actually correct -- the header format (and therefore status-cell recognition) is identical regardless of which scheme matched a file's own name.

`folderadr` already has an equivalent guard (`reject_folderadr_change_if_decisions_exist`, itself a deliberate adrpy-ai divergence from AdrPlus, which has no such guard either) -- no equivalent exists for status labels or `separator`.

A fully structural fix for the status half (splitting Accepted/Rejected into separate, positionally-distinct header slots, eliminating text matching entirely) was considered and would work, but requires changing the physical header layout -- breaking byte-compatibility with AdrPlus in both codebases, plus a migration story for every already-written decision on both sides. No equivalent structural fix exists for `separator` at all -- it is the literal delimiter inside a filename, with no spare, ignored space to hide a marker in (unlike a header cell's trailing space after a date). Is there a fix that removes both fragilities without a format-breaking migration?

## Decision Drivers

* Confirmed live, twice, independently: changing a status label, or changing `separator`, on a repository with existing decisions breaks recognition of those decisions immediately, with no warning -- both are real, reproducible defects, not hypothetical ones.
* `header.py`'s own stated design goal is a byte-for-byte replica of the reference tool's format -- any fix that changes what a human sees in the file, or what AdrPlus itself can parse, is a real compatibility cost, not a free one. This constrains the status fix; it does not apply the same way to `separator`, which has no marker-hiding option regardless.
* The date-parsing logic in both this port and the real AdrPlus tool (`Helper.ParseStatusLine`, `_parse_status_cell`) already only inspects text between the first `(` and the first `)` in a status cell -- anything after the closing `)` is ignored by both parsers today, and this is already exploited in production: the Superseded row's own `superseded_by_file` suffix (`" : 002"`) is written and read exactly this way (`core/header.py`'s `_status_row`/`mark_superseded`).
* `statusacc`/`statusrej`/etc. exist specifically so the visible, human-facing word in a decision file can be written in the repository's own configured language -- a fix that makes the tool always write/expect a fixed English word defeats the reason those fields exist at all.
* `separator` is purely a filename delimiter with no display/translation purpose of its own -- there is no equivalent "preserve the human-facing word" constraint for it, which is exactly why no marker-based option exists or is needed for it; a guard is the only available mechanism.
* `scan_decisions` (already used by `folderadr`'s own guard) already recognizes decisions using whatever config it is given -- scanning with the *old* config, before a guarded field commits, answers "would this change affect anything real" correctly for both fields with the same one call, no field-specific scanning logic needed.
* This affects two independently-maintained codebases (adrpy-ai and the real AdrPlus) for the status-marker half; a decision that only one side implements silently reintroduces the exact fragility this ADR exists to close, the moment a file crosses from one tool to the other. The `separator`/`migrationpattern` guard is adrpy-ai-only (AdrPlus has no equivalent guard for any of these fields, and adopting one there is not required for adrpy-ai's own guard to be correct; AdrPlus also has no `migrationpattern`/legacy-scheme concept at all).
* (V02) A guard mechanism reused for a new, higher-stakes field inherits that mechanism's own scope, unverified in the new direction until checked: V01's blanket "any decision blocks it" was verified safe as a conservative-but-imprecise check for `separator`, but re-verifying it against `migrationpattern`'s actual dependency (only the legacy scheme) showed the blanket shape itself needed correcting, not just extending.
* (V02) A marker match that's exact-case-only silently reopens the fragility this ADR closes the moment a hand edit (or any process other than this tool) changes only the marker's letter case -- confirmed live: `<!-- accepted -->` failed the original match and fell back to label-text matching with zero signal that this had happened.

## Considered Options

* Split Accepted/Rejected into two separate, positionally-distinct header rows, eliminating all status text-matching -- requires a header format version change and a coordinated breaking change in both adrpy-ai and AdrPlus, plus a migration story for existing files on both sides. No equivalent exists for `separator`/`migrationpattern` regardless.
* Append a fixed, non-translatable canonical marker (an HTML comment, e.g. `<!-- Accepted -->`) after the closing `)` of each status row's cell, in the same trailing space both parsers already ignore for date purposes -- read it when present; fall back to today's label-text match when absent (a file written before this change exists). Requires the same convention adopted in AdrPlus so files stay portable both ways, but changes neither the header's line count nor its currently-visible text. Applies only to the status fields -- a filename has no equivalent ignored space to hide a marker in, for either naming scheme.
* Add a guard blocking a config change whenever the repository already has recognized decisions and the change would affect how they are recognized (mirrors `reject_folderadr_change_if_decisions_exist`), without changing the file format or parser at all. Covers status labels, `separator`, and (V02) `migrationpattern` with the same mechanism, since `scan_decisions` (the same function the guard scans with) already tags every result with its naming scheme.
* (V01, superseded by the next option) One flat, blanket field list: any recognized decision (regardless of scheme) blocks a change to any guarded field. Simplest to implement, but imprecise for scheme-specific fields.
* (V02, chosen) A scheme-aware guard: status labels block on any recognized decision (scheme-independent, since header content is read the same way for both schemes); `separator` blocks only if a CURRENT-scheme decision exists; `migrationpattern` blocks only if a LEGACY-scheme decision exists. Same shared `scan_decisions` call as V01 (already scheme-tagged), just grouped and evaluated per field's real dependency instead of one flat list.
* Also build a migration path (rename every existing decision's filename to match a new `separator`/`migrationpattern`, atomically, under the repository lock) instead of a permanent block -- considered and explicitly deferred, not chosen now: real scope on the order of the existing `migrate` command (family/supersede-chain-aware, atomic, needs its own design), for a need (changing an established naming convention after decisions already exist) that has not been requested independently of this ADR.
* Do nothing; document the risk and leave label/separator/migrationpattern changes on an existing repository as an accepted, unguarded risk.
* (V02) Marker matching: case-sensitive (V01's original) vs. case-insensitive with normalization back to the canonical case before use elsewhere. Chosen: case-insensitive -- the marker's own value space is a small, fixed, closed set (Proposed/Accepted/Rejected/Superseded), so tolerating case variation introduces no new ambiguity, while exact-case-only left a real, confirmed blind spot for zero benefit.

## Decision Outcome

Chosen (V01, unchanged): **the hidden canonical marker for status labels, combined with one existing-decisions guard covering fields that affect recognition** -- adopted together, not as alternatives, because they close different halves of two related problems, and the guard's own mechanism (scan with the pre-change config) is shared across every guarded field.

Chosen (V02, corrections): the guard now also covers `migrationpattern`, and is **scheme-aware** rather than blanket -- status labels still block on any recognized decision (scheme-independent), `separator` blocks only when a CURRENT-scheme decision exists, `migrationpattern` blocks only when a LEGACY-scheme decision exists. The marker's own match is now case-insensitive (normalized back to canonical case before use), closing the confirmed case-sensitivity blind spot.

The marker closes the status fragility at the root for every decision written *after* this change exists: recognition no longer depends on the repository's current label configuration at all, so a later label/language change can never again break a file written under this scheme, on either adrpy-ai or AdrPlus. It does this without moving a single line of the header, without changing what a human reading the raw file sees (the configured, translated word stays exactly where it is), and without AdrPlus needing to change how it renders anything -- it only needs to tolerate (or itself write) trailing content after the date's closing `)`, which its own parser already does today, unmodified, confirmed directly in its source. No equivalent marker exists for `separator`/`migrationpattern` -- a filename delimiter has no spare, ignored space to hide anything in, for either scheme.

The guard closes the rest: for status labels, every decision written *before* the marker exists has none, and still depends on label-text matching until rewritten by a later command; for `separator`/`migrationpattern`, there is no marker option at all, ever, so the guard is the *entire* fix for those fields, not a stopgap for a transition period. The guard makes any guarded change on a repository with an affected recognized decision fail closed (a new, structured failure code naming exactly which field(s) triggered it) instead of silently breaking those files, the same way `folderadr` already fails closed today. For `separator` and `migrationpattern` specifically, this is a **permanent** block once the scheme each one governs has any decision -- no migration path is provided (see Considered Options); this mirrors `folderadr`'s own existing, accepted limitation (it also blocks permanently, with no migration path), so this is not a new kind of gap, it is consistent with precedent already accepted for this project.

The scheme-aware design (rather than V01's blanket check) matters for more than just `migrationpattern`'s own new coverage: it also corrects `separator`'s own pre-existing imprecision (V01 blocked a `separator` change even on a repository with only legacy-scheme decisions, where `separator` has zero bearing) -- a repository that mixes both schemes, or one that only ever uses one of them, now gets exactly the protection each guarded field's own real dependency calls for, no more and no less.

The fully structural option (separate Accepted/Rejected rows) is not chosen: it solves the status half of the problem but at the cost of a format-version migration in two codebases, for a fragility the marker already closes without that cost, and it has no bearing on `separator`/`migrationpattern` at all.

### Positive Consequences

* Every decision written after this change is adopted is permanently immune to a later status-label/language change, on either tool, with zero migration needed for it specifically.
* No change to the header's line count, to what a human sees in the raw file, or to AdrPlus's own rendering -- the marker rides in space both parsers already discard today.
* The guard gives every repository, old or new, an explicit, structured refusal instead of silent breakage the moment someone tries to change a status label, `separator`, or `migrationpattern` with an affected decision already on disk -- closing the exact class of risk, not just the instances that started this discussion.
* One shared guard function, one shared scan call (`scan_decisions` with the pre-change config, already scheme-tagged), covers all three field groups -- no per-field scanning logic to duplicate or drift.
* (V02) A repository using only one naming scheme is no longer blocked from changing the OTHER scheme's own naming field -- closes a real, if narrow, usability regression V01 would otherwise have shipped for `migrationpattern`, and corrects one V01 already had for `separator`.
* (V02) A hand-edited marker with the wrong case is no longer a silent, zero-signal reversion to label-text matching.

### Negative Consequences

* Decisions written before the marker exists carry none and remain dependent on label-text matching until rewritten by a later command -- the guard mitigates the blast radius but does not retroactively immunize those files.
* Requires the same marker convention to be implemented in AdrPlus (C#) for full round-trip safety between the two tools; until that lands, a file written by adrpy-ai with the marker is still readable by AdrPlus today (the marker is inert to it), but AdrPlus's own writes will not carry it until it adopts the same convention.
* `separator` and `migrationpattern`, once the scheme each one governs has any decision, can never be changed again through the tool -- there is no migration path, by explicit choice (see Considered Options). Someone who wants a different separator/migrationpattern on an established repository has no supported way to get it.
* Four mechanisms to reason about instead of one (marker presence, case-insensitive normalization, and three independent scheme-scoped trigger conditions inside one guard) -- a maintainer needs all of this ADR to understand why each exists.
* The guard now depends on `scan_decisions`'s own per-result scheme tag being correct -- a latent bug in scheme detection (`parse_any_filename`'s current-vs-legacy precedence) would now also silently misroute which guarded fields it protects, a dependency that didn't exist under V01's scheme-blind blanket check.

## Pros and Cons of the Options

### Split Accepted/Rejected into separate header rows

* Good, because it eliminates status text-matching completely, for every file, old and new alike, once migrated.
* Bad, because it breaks byte-compatibility with AdrPlus's current header format in both codebases.
* Bad, because it requires a real migration story for every already-written decision, on both sides.
* Bad, because it does nothing for `separator`/`migrationpattern`, which have the same class of risk but no header row to restructure.

### Hidden canonical marker after the date

* Good, because it closes the status fragility at the root for all new writes, with no format or visible-text change.
* Good, because the mechanism it relies on (trailing content after `)` being ignored) is already proven in production via `superseded_by_file`.
* Bad, because it protects only files written after adoption -- existing files still need the guard below.
* Bad, because it has no equivalent for `separator`/`migrationpattern` -- a filename delimiter, unlike a header cell, has no ignored trailing space to hide a marker in, for either naming scheme.

### Existing-decisions guard -- V01's blanket check (any scheme blocks any guarded field)

* Good, because it is the smallest possible change for `separator` -- no parser change, no new file content, mirrors an already-accepted pattern (`folderadr`), and is the only option available for that field at all.
* Good, because one shared function/scan closes every guarded field at once, with no per-field scanning logic.
* Bad, because for status labels it only prevents the label-change trigger -- it does not remove the underlying text-matching fragility itself for files that predate the marker.
* Bad, because it is imprecise: it blocks `separator` changes on legacy-only repositories (harmless there) and would have blocked `migrationpattern` changes on current-scheme-only repositories (also harmless) had it simply been extended to cover that field too.

### Existing-decisions guard -- V02's scheme-aware check (chosen)

* Good, because it keeps every advantage of V01's guard (smallest possible change for the fields with no marker option, one shared function/scan, mirrors `folderadr`'s own precedent) while fixing its imprecision.
* Good, because it correctly extends to `migrationpattern` without introducing a symmetric new imprecision.
* Bad, because for status labels it only prevents the label-change trigger -- it does not remove the underlying text-matching fragility itself for files that predate the marker (same limitation as V01, unchanged).
* Bad, because for `separator`/`migrationpattern` it is a permanent block once the scheme each one governs has any decision, with no migration path -- accepted here as consistent with `folderadr`'s own existing precedent, not treated as a gap unique to this decision.
* Bad, because it is more code to reason about than a flat blanket list (three grouped checks instead of one), and now depends on `scan_decisions`'s own scheme tag being correct.

### Migration path for `separator`/`migrationpattern` (rename existing files instead of blocking)

* Good, because it would be the only option that actually lets a repository change its separator/migrationpattern after decisions exist, instead of permanently refusing.
* Bad, because it is real, non-trivial scope -- family/supersede-chain-aware, atomic-under-lock renaming, on the order of the existing `migrate` command -- for a need not yet requested on its own.
* Bad, because getting the family/chain bookkeeping wrong during a bulk rename risks the exact kind of corruption this whole ADR exists to prevent, for a feature that is not required to close the defect this ADR is about.

### Do nothing

* Good, because it requires no work at all.
* Bad, because all three defects are already confirmed live and reproducible; leaving them undocumented and unguarded means the next label, language, separator, or migrationpattern change silently repeats one of them.

### Marker matching: case-sensitive (V01) vs. case-insensitive (V02, chosen)

* Case-sensitive -- Good, because it is the simplest possible match. Bad, because a hand-edited marker with the wrong case silently and invisibly falls back to label-text matching, confirmed live as a real (if narrow) gap.
* Case-insensitive -- Good, because the marker's value space is small and fixed, so tolerating case variation introduces no new ambiguity; closes the confirmed gap at the cost of one line of code (`re.IGNORECASE` plus normalizing the match back to canonical case for every downstream consumer that requires it).

