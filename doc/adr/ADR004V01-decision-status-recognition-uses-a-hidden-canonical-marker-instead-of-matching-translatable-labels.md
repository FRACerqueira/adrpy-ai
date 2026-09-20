<!-- Do not remove this comment, lines and table (1-12) -->
|Adr-Plus Fields|Values|
|--|--|
|File title md|Decision status recognition uses a hidden canonical marker instead of matching translatable labels|
|Version|01|
|Revision||
|Scope|header|
|Domain|correctness|
|Created|Proposed (2026-09-20)|
|Changed|Accepted (2026-09-20)|
|Superseded||
<!-- Do not remove this comment, lines and table (1-12) -->
---
# Decision status recognition uses a hidden canonical marker instead of matching translatable labels

## Deciders

* Deciders: Fernando Cerqueira (repo owner), decided directly through a design discussion that started from a globalization/onboarding question and surfaced a live parsing bug along the way.

Technical Story: a direct architecture discussion (not a pre-release-audit round) that began with "how does a first-time user discover and set the repository's language/config," moved into "what happens if `--language`/`config` changes a status label after decisions already exist," and was confirmed live: changing `config --statusnew` on a repository with an existing decision made that decision `is_valid: false` -- the tool stopped recognizing it entirely.

## Context and Problem Statement

`core/header.py` recognizes a decision's status (Proposed/Accepted/Rejected/Superseded) by matching the text inside each header row's status cell against the repository's own **current** `statusnew`/`statusacc`/`statusrej`/`statussup` config values (`_parse_status_cell`'s `label_to_status` dict, rebuilt fresh on every parse). This is a byte-for-byte replica of the real AdrPlus (C#) tool's own design (confirmed directly in its source: `AdrPlusRepoConfig.StatusMapping` and `Helper.ParseStatusLine`, `C:\Sources\AdrPlus\src\AdrPlus\Domain\AdrPlusRepoConfig.cs:179-186` and `Core\Helper.cs:253-283`) -- not a defect introduced by this port.

The consequence, confirmed live on this project: if a repository's status labels change after decisions already exist -- via `config --statusnew`/etc. directly, or via any future `--language`/`installconfig --language` convenience seeding a different label set -- every existing decision whose header cell still holds the *old* text stops matching the *current* config, and is silently reclassified `is_valid: false`. The tool loses the ability to recognize its own, previously-valid decisions. `folderadr` already has an equivalent guard (`reject_folderadr_change_if_decisions_exist`, itself a deliberate adrpy-ai divergence from AdrPlus, which has no such guard either) -- no equivalent exists for status/header labels.

A fully structural fix (splitting Accepted/Rejected into separate, positionally-distinct header slots, eliminating text matching entirely) was considered and would work, but requires changing the physical header layout -- breaking byte-compatibility with AdrPlus in both codebases, plus a migration story for every already-written decision on both sides. Is there a fix that removes the fragility without that cost?

## Decision Drivers

* Confirmed live: changing a single status label on a repository with existing decisions breaks recognition of those decisions immediately, with no warning -- this is a real, reproducible defect, not a hypothetical one.
* `header.py`'s own stated design goal is a byte-for-byte replica of the reference tool's format -- any fix that changes what a human sees in the file, or what AdrPlus itself can parse, is a real compatibility cost, not a free one.
* The date-parsing logic in both this port and the real AdrPlus tool (`Helper.ParseStatusLine`, `_parse_status_cell`) already only inspects text between the first `(` and the first `)` in a status cell -- anything after the closing `)` is ignored by both parsers today, and this is already exploited in production: the Superseded row's own `superseded_by_file` suffix (`" : 002"`) is written and read exactly this way (`core/header.py`'s `_status_row`/`mark_superseded`).
* `statusacc`/`statusrej`/etc. exist specifically so the visible, human-facing word in a decision file can be written in the repository's own configured language -- a fix that makes the tool always write/expect a fixed English word defeats the reason those fields exist at all.
* This affects two independently-maintained codebases (adrpy-ai and the real AdrPlus); a decision that only one side implements silently reintroduces the exact fragility this ADR exists to close, the moment a file crosses from one tool to the other.

## Considered Options

* Split Accepted/Rejected into two separate, positionally-distinct header rows, eliminating all status text-matching -- requires a header format version change and a coordinated breaking change in both adrpy-ai and AdrPlus, plus a migration story for existing files on both sides.
* Append a fixed, non-translatable canonical marker (an HTML comment, e.g. `<!-- Accepted -->`) after the closing `)` of the Changed row's status cell, in the same trailing space both parsers already ignore for date purposes -- read it when present; fall back to today's label-text match when absent (a file written before this change exists). Requires the same convention adopted in AdrPlus so files stay portable both ways, but changes neither the header's line count nor its currently-visible text.
* Add a guard blocking a status/header label config change whenever the repository already has recognized decisions (mirrors `reject_folderadr_change_if_decisions_exist`), without changing the file format or parser at all.
* Do nothing; document the risk and leave label changes on an existing repository as an accepted, unguarded risk.

## Decision Outcome

Chosen: **the hidden canonical marker (option 2), combined with the existing-decisions guard (option 3)** -- adopted together, not as alternatives, because they close two different halves of the same problem.

The marker closes the fragility at the root for every decision written *after* this change exists: recognition no longer depends on the repository's current label configuration at all, so a later label/language change can never again break a file written under this scheme, on either adrpy-ai or AdrPlus. It does this without moving a single line of the header, without changing what a human reading the raw file sees (the configured, translated word stays exactly where it is), and without AdrPlus needing to change how it renders anything -- it only needs to tolerate (or itself write) trailing content after the date's closing `)`, which its own parser already does today, unmodified, confirmed directly in its source.

The guard closes the other half: every decision written *before* this change exists has no marker, and still depends on label-text matching until it is rewritten by some later command. The guard makes a label/language change on such a repository fail closed (a new, structured failure code) instead of silently breaking those files, the same way `folderadr` already fails closed today.

The fully structural option (separate Accepted/Rejected rows) is not chosen: it solves the same problem but at the cost of a format-version migration in two codebases, for a fragility the marker+guard combination already closes without that cost.

### Positive Consequences

* Every decision written after this change is adopted is permanently immune to a later label/language change, on either tool, with zero migration needed for it specifically.
* No change to the header's line count, to what a human sees in the raw file, or to AdrPlus's own rendering -- the marker rides in space both parsers already discard today.
* The guard gives every repository, old or new, an explicit, structured refusal instead of silent breakage the moment someone tries to change a label with decisions already on disk.

### Negative Consequences

* Decisions written before this change carries no marker and remains dependent on label-text matching until rewritten by a later command (or migrated explicitly) -- the guard mitigates the blast radius but does not retroactively immunize those files.
* Requires the same convention to be implemented in AdrPlus (C#) for full round-trip safety between the two tools; until that lands, a file written by adrpy-ai with the marker is still readable by AdrPlus today (the marker is inert to it), but AdrPlus's own writes will not carry it until it adopts the same convention.
* Two mechanisms (marker presence, and the guard) to reason about instead of one -- a maintainer needs both halves of this ADR to understand why either exists.

## Pros and Cons of the Options

### Split Accepted/Rejected into separate header rows

* Good, because it eliminates status text-matching completely, for every file, old and new alike, once migrated.
* Bad, because it breaks byte-compatibility with AdrPlus's current header format in both codebases.
* Bad, because it requires a real migration story for every already-written decision, on both sides.

### Hidden canonical marker after the date

* Good, because it closes the fragility at the root for all new writes, with no format or visible-text change.
* Good, because the mechanism it relies on (trailing content after `)` being ignored) is already proven in production via `superseded_by_file`.
* Bad, because it protects only files written after adoption -- existing files still need the guard below.

### Existing-decisions guard only (no marker)

* Good, because it is the smallest possible change -- no parser change, no new file content, mirrors an already-accepted pattern (`folderadr`).
* Bad, because it only prevents the label-change trigger -- it does not remove the underlying text-matching fragility itself, which remains latent.

### Do nothing

* Good, because it requires no work at all.
* Bad, because the defect is already confirmed live and reproducible; leaving it undocumented and unguarded means the next label/language change silently repeats it.

