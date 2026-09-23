<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Decision status recognition uses a hidden canonical marker; status labels and the filename separator both gain an existing-decisions guard|
|Version|01|
|Revision||
|Scope|header|
|Domain|correctness|
|Created|Proposed (2026-09-20) <!-- Proposed -->|
|Changed|Accepted (2026-09-20) <!-- Accepted -->|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Decision status recognition uses a hidden canonical marker; status labels and the filename separator both gain an existing-decisions guard

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided directly through a design discussion that started from a globalization/onboarding question and surfaced a live parsing bug along the way, then widened in scope when the same question ("what else has this shape?") was asked deliberately before implementation started.

Technical Story: a direct architecture discussion (not a pre-release-audit round) that began with "how does a first-time user discover and set the repository's language/config," moved into "what happens if `--language`/`config` changes a status label after decisions already exist," and was confirmed live: changing `config --statusnew` on a repository with an existing decision made that decision `is_valid: false` -- the tool stopped recognizing it entirely. Before implementation, the same question was asked of every other config field: does anything else determine whether an existing decision is *recognized at all* by comparing against the repository's *current* config? One more field was found and confirmed live the same way: `separator`.

## Context and Problem Statement

Two independent config fields determine whether an already-written decision is recognized at all, by comparing something already fixed in the file against the repository's **current** config value for that field, re-read fresh on every parse:

1. **Status labels** (`statusnew`/`statusacc`/`statusrej`/`statussup`): `core/header.py`'s `_parse_status_cell` matches each status row's cell text against these four values (`label_to_status`, rebuilt fresh every parse) to recognize Proposed/Accepted/Rejected/Superseded.
2. **`separator`**: `core/naming.py`'s `parse_filename` locates the boundary between the number/version/revision segment and the title via `name.find(config.separator)` -- confirmed live: changing `config --separator` from `-` to `_` on a repository with one existing decision made `explore` report that file with `scheme: null, number: 0, title: null` -- the filename stops being recognized at all (the header content itself stays readable; only the file's identity, derived from its name, is lost).

Both are byte-for-byte replicas of the real AdrPlus (C#) tool's own design (confirmed directly in its source: status matching in `AdrPlusRepoConfig.StatusMapping`/`Helper.ParseStatusLine`, `C:\Sources\AdrPlus\src\AdrPlus\Domain\AdrPlusRepoConfig.cs:179-186` and `Core\Helper.cs:253-283`; separator matching in `AdrService.cs:575`, `supersedeParts[0].IndexOf(separator, ...)`) -- neither is a defect introduced by this port; AdrPlus has the identical fragility in both cases.

Every other config field was checked the same way before settling scope, to close the class rather than the two instances already found: `prefix` (confirmed live: safe, the filename regex captures any prefix without comparing it to config), `casetransform` (safe, title is extracted as literal text, never re-cased for comparison), `lenseq`/`lenversion`/`lenrevision` (safe by pre-existing, deliberate design -- `core/naming.py`'s own docstring already states digit runs are matched at variable length for exactly this reason), the 11 header row labels plus `headerdisclaimer` (safe, positional only, never parsed), `migrationpattern` (a different nature -- it describes a pre-existing external convention for files this tool never wrote, not a value this tool's own writes depend on staying stable), and `template` (safe, never compared back, only used as initial content for a new decision).

`folderadr` already has an equivalent guard (`reject_folderadr_change_if_decisions_exist`, itself a deliberate adrpy-ai divergence from AdrPlus, which has no such guard either) -- no equivalent exists for status labels or `separator`.

A fully structural fix for the status half (splitting Accepted/Rejected into separate, positionally-distinct header slots, eliminating text matching entirely) was considered and would work, but requires changing the physical header layout -- breaking byte-compatibility with AdrPlus in both codebases, plus a migration story for every already-written decision on both sides. No equivalent structural fix exists for `separator` at all -- it is the literal delimiter inside a filename, with no spare, ignored space to hide a marker in (unlike a header cell's trailing space after a date). Is there a fix that removes both fragilities without a format-breaking migration?

## Decision Drivers

* Confirmed live, twice, independently: changing a status label, or changing `separator`, on a repository with existing decisions breaks recognition of those decisions immediately, with no warning -- both are real, reproducible defects, not hypothetical ones.
* `header.py`'s own stated design goal is a byte-for-byte replica of the reference tool's format -- any fix that changes what a human sees in the file, or what AdrPlus itself can parse, is a real compatibility cost, not a free one. This constrains the status fix; it does not apply the same way to `separator`, which has no marker-hiding option regardless.
* The date-parsing logic in both this port and the real AdrPlus tool (`Helper.ParseStatusLine`, `_parse_status_cell`) already only inspects text between the first `(` and the first `)` in a status cell -- anything after the closing `)` is ignored by both parsers today, and this is already exploited in production: the Superseded row's own `superseded_by_file` suffix (`" : 002"`) is written and read exactly this way (`core/header.py`'s `_status_row`/`mark_superseded`).
* `statusacc`/`statusrej`/etc. exist specifically so the visible, human-facing word in a decision file can be written in the repository's own configured language -- a fix that makes the tool always write/expect a fixed English word defeats the reason those fields exist at all.
* `separator` is purely a filename delimiter with no display/translation purpose of its own -- there is no equivalent "preserve the human-facing word" constraint for it, which is exactly why no marker-based option exists or is needed for it; a guard is the only available mechanism.
* `scan_decisions` (already used by `folderadr`'s own guard) already recognizes decisions using whatever config it is given -- scanning with the *old* config, before a guarded field commits, answers "would this change affect anything real" correctly for both fields with the same one call, no field-specific scanning logic needed.
* This affects two independently-maintained codebases (adrpy-ai and the real AdrPlus) for the status-marker half; a decision that only one side implements silently reintroduces the exact fragility this ADR exists to close, the moment a file crosses from one tool to the other. The `separator` guard is adrpy-ai-only (AdrPlus has no equivalent guard for either field, and adopting one there is not required for adrpy-ai's own guard to be correct).

## Considered Options

* Split Accepted/Rejected into two separate, positionally-distinct header rows, eliminating all status text-matching -- requires a header format version change and a coordinated breaking change in both adrpy-ai and AdrPlus, plus a migration story for existing files on both sides. No equivalent exists for `separator` regardless.
* Append a fixed, non-translatable canonical marker (an HTML comment, e.g. `<!-- Accepted -->`) after the closing `)` of each status row's cell, in the same trailing space both parsers already ignore for date purposes -- read it when present; fall back to today's label-text match when absent (a file written before this change exists). Requires the same convention adopted in AdrPlus so files stay portable both ways, but changes neither the header's line count nor its currently-visible text. Applies only to the status fields -- a filename has no equivalent ignored space to hide a marker in.
* Add a guard blocking a config change whenever the repository already has recognized decisions and the change would affect how they are recognized (mirrors `reject_folderadr_change_if_decisions_exist`), without changing the file format or parser at all. Covers status labels and `separator` with the same mechanism, since `scan_decisions` (the same function the guard scans with) already depends on both.
* Also build a migration path (rename every existing decision's filename to match a new `separator`, atomically, under the repository lock) instead of a permanent block -- considered and explicitly deferred, not chosen now: real scope on the order of the existing `migrate` command (family/supersede-chain-aware, atomic, needs its own design), for a need (changing an established naming convention after decisions already exist) that has not been requested independently of this ADR.
* Do nothing; document the risk and leave label/separator changes on an existing repository as an accepted, unguarded risk.

## Decision Outcome

Chosen: **the hidden canonical marker for status labels, combined with one existing-decisions guard covering both status labels and `separator`** -- adopted together, not as alternatives, because they close different halves of two related problems, and the guard's own mechanism (scan with the pre-change config) is identical for both fields.

The marker closes the status fragility at the root for every decision written *after* this change exists: recognition no longer depends on the repository's current label configuration at all, so a later label/language change can never again break a file written under this scheme, on either adrpy-ai or AdrPlus. It does this without moving a single line of the header, without changing what a human reading the raw file sees (the configured, translated word stays exactly where it is), and without AdrPlus needing to change how it renders anything -- it only needs to tolerate (or itself write) trailing content after the date's closing `)`, which its own parser already does today, unmodified, confirmed directly in its source. No equivalent marker exists for `separator` -- a filename delimiter has no spare, ignored space to hide anything in.

The guard closes the rest: for status labels, every decision written *before* the marker exists has none, and still depends on label-text matching until rewritten by a later command; for `separator`, there is no marker option at all, ever, so the guard is the *entire* fix for that field, not a stopgap for a transition period. The guard makes either kind of change on a repository with existing decisions fail closed (a new, structured failure code naming exactly which field(s) triggered it) instead of silently breaking those files, the same way `folderadr` already fails closed today. For `separator` specifically, this is a **permanent** block once any decision exists -- no migration path is provided (see Considered Options); this mirrors `folderadr`'s own existing, accepted limitation (it also blocks permanently, with no migration path), so this is not a new kind of gap, it is consistent with precedent already accepted for this project.

The fully structural option (separate Accepted/Rejected rows) is not chosen: it solves the status half of the problem but at the cost of a format-version migration in two codebases, for a fragility the marker already closes without that cost, and it has no bearing on `separator` at all.

### Positive Consequences

* Every decision written after this change is adopted is permanently immune to a later status-label/language change, on either tool, with zero migration needed for it specifically.
* No change to the header's line count, to what a human sees in the raw file, or to AdrPlus's own rendering -- the marker rides in space both parsers already discard today.
* The guard gives every repository, old or new, an explicit, structured refusal instead of silent breakage the moment someone tries to change a status label or `separator` with decisions already on disk -- closing the exact class of risk, not just the one instance (status) that started this discussion.
* One shared guard function, one shared scan call (`scan_decisions` with the pre-change config), covers both fields -- no per-field scanning logic to duplicate or drift.

### Negative Consequences

* Decisions written before the marker exists carry none and remain dependent on label-text matching until rewritten by a later command -- the guard mitigates the blast radius but does not retroactively immunize those files.
* Requires the same marker convention to be implemented in AdrPlus (C#) for full round-trip safety between the two tools; until that lands, a file written by adrpy-ai with the marker is still readable by AdrPlus today (the marker is inert to it), but AdrPlus's own writes will not carry it until it adopts the same convention.
* `separator`, once any decision exists, can never be changed again through the tool -- there is no migration path, by explicit choice (see Considered Options). Someone who wants a different separator on an established repository has no supported way to get it.
* Three mechanisms to reason about instead of one (marker presence, and two independent trigger conditions inside one guard) -- a maintainer needs all of this ADR to understand why each exists.

## Pros and Cons of the Options

### Split Accepted/Rejected into separate header rows

* Good, because it eliminates status text-matching completely, for every file, old and new alike, once migrated.
* Bad, because it breaks byte-compatibility with AdrPlus's current header format in both codebases.
* Bad, because it requires a real migration story for every already-written decision, on both sides.
* Bad, because it does nothing for `separator`, which has the same class of risk but no header row to restructure.

### Hidden canonical marker after the date

* Good, because it closes the status fragility at the root for all new writes, with no format or visible-text change.
* Good, because the mechanism it relies on (trailing content after `)` being ignored) is already proven in production via `superseded_by_file`.
* Bad, because it protects only files written after adoption -- existing files still need the guard below.
* Bad, because it has no equivalent for `separator` -- a filename delimiter, unlike a header cell, has no ignored trailing space to hide a marker in.

### Existing-decisions guard, covering both status labels and separator

* Good, because it is the smallest possible change for `separator` -- no parser change, no new file content, mirrors an already-accepted pattern (`folderadr`), and is the only option available for that field at all.
* Good, because one shared function/scan closes both fields at once, with no per-field duplication.
* Bad, because for status labels it only prevents the label-change trigger -- it does not remove the underlying text-matching fragility itself for files that predate the marker.
* Bad, because for `separator` it is a permanent block once any decision exists, with no migration path -- accepted here as consistent with `folderadr`'s own existing precedent, not treated as a gap unique to this decision.

### Migration path for `separator` (rename existing files instead of blocking)

* Good, because it would be the only option that actually lets a repository change its separator after decisions exist, instead of permanently refusing.
* Bad, because it is real, non-trivial scope -- family/supersede-chain-aware, atomic-under-lock renaming, on the order of the existing `migrate` command -- for a need not yet requested on its own.
* Bad, because getting the family/chain bookkeeping wrong during a bulk rename risks the exact kind of corruption this whole ADR exists to prevent, for a feature that is not required to close the defect this ADR is about.

### Do nothing

* Good, because it requires no work at all.
* Bad, because both defects are already confirmed live and reproducible; leaving them undocumented and unguarded means the next label, language, or separator change silently repeats one of them.

