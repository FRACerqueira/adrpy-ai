# migrate refuses immediately when migrationpattern is empty, with no install-level fallback

**Reopen-when:** an install-level/app-config module exists in adrpy-ai

When the repo's own
`migrationpattern` is empty, a fallback to an
install-level default would let `migrate` try once more before
giving up.
adrpy has neither the install-level config
layer nor that two-stage fallback: it refuses immediately with
`migration-pattern-not-configured`.

**Why deferred, not accepted as final:** the missing piece is
infrastructural (no install-level/app-config module exists in adrpy yet),
not a considered design choice — kept as the simplest correct interim
behavior (refuse clearly instead of silently doing nothing).

**Reopening condition:** revisit once adrpy has an install-level config
module; wire in a two-stage fallback (repo pattern -> install-level
default -> generic "nothing found" if both are empty).
