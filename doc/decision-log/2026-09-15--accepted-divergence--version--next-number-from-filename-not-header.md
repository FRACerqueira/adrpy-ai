# version's next version number derives from the filename; AdrPlus 1.0.0 reads the header cell

`cli/version.py` derives the number for a new version from
`latest_parsed.version + 1`, where `latest_parsed` comes from parsing the
**filename** of the latest family member. The real tool's
`AdrService.cs:211-215` instead overwrites that value with whatever the
**header's own `|Version|` cell** says, once it has been read.

**Why kept as-is, not changed to match:** in the normal case the two
agree, so this only matters when a file's header and filename have
drifted out of sync (a hand-edited header, or a file from another tool).
Confirmed live (Milestone 8 audit, fidelity finding F6) that adopting the
C# behavior can make `version` **fail** in a case adrpy-ai currently
handles correctly: with a family of 24 versions all sharing the same
header-recorded version number (e.g. every header says `01` due to a
drifted/hand-edited state), the real tool's header-driven logic would
retry the same already-existing filename (`V02`) instead of the true
next one (`V25`). Deriving from the filename never produces a number
that collides with an existing file, at the cost of this one drifted-
state divergence from the original. Escalated and confirmed with the
user.

Architectural review (Round 43): adrpy is now the reference and AdrPlus will mirror it; deriving from the filename is adrpy's rule. The reason stands.
