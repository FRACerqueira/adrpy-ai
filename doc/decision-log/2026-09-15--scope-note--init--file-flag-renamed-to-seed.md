# init's config flag is --seed, not --file

adrpy-ai at first used `-f/--file` for two unrelated things: the decision
file to mutate (approve/reject/undo/supersede/version/revise) and the
config JSON to seed a new repository with (`init`).
Confirmed with the user: renamed `init`'s
flag to `--seed` (short alias `-s`), removing the collision — every
other command's `--file` now unambiguously means "the decision file."

**Why renamed:** an agent generalizing the
meaning of `--file` from the 6 commands that share it could reasonably
(and wrongly) assume `init --file X` also expects a decision file. The
command's own description disambiguates this, but a distinct
flag name removes the ambiguity even for an agent that doesn't read the
description first.

Architectural review (Round 43): the reason stands.
