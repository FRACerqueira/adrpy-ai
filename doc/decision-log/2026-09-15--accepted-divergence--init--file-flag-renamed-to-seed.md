# init's config flag is --seed, not AdrPlus 1.0.0's --file

The real adrplus uses `-f/--file` for two unrelated things: the decision
file to mutate (approve/reject/undo/supersede/version/revise) and the
config JSON to seed a new repository with (`init`). adrpy-ai inherited
the same collision at first. Confirmed with the user: renamed `init`'s
flag to `--seed` (short alias `-s`), removing the collision — every
other command's `--file` now unambiguously means "the decision file."

**Why kept as a deliberate divergence:** an agent generalizing the
meaning of `--file` from the 6 commands that share it could reasonably
(and wrongly) assume `init --file X` also expects a decision file. The
real tool's own descriptions disambiguate this today, but a distinct
flag name removes the ambiguity even for an agent that doesn't read the
description first — at the cost of no longer matching the real tool's
own flag name for `init`.

Architectural review (Round 43): adrpy is now the reference and AdrPlus will mirror it; `--seed` is adrpy's flag, and AdrPlus 1.0.0 still names it `--file`. The reason stands.
