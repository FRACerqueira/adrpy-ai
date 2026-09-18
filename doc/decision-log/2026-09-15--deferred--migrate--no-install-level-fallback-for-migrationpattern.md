# migrate refuses immediately when migrationpattern is empty, with no install-level fallback

**Reopen-when:** an install-level/app-config module exists in adrpy-ai

Confirmed against `MigrateCommandHandler.cs:97-105`: when the repo's own
`migrationpattern` is empty, the real adrplus first tries an
install-level shared default (`config --migrate --file <json>`) before
giving up — and even then, it doesn't fail with a dedicated "not
configured" error, it just proceeds and fails later with a generic "no
valid ADR found to migrate" (`NotFoundValidMigrateADR`), since nothing
matches the empty pattern. adrpy has neither the install-level config
layer nor that two-stage fallback: it refuses immediately with
`migration-pattern-not-configured`.

**Why deferred, not accepted as final:** the missing piece is
infrastructural (no install-level/app-config module exists in adrpy yet),
not a considered design choice — kept as the simplest correct interim
behavior (refuse clearly instead of silently doing nothing).

**Reopening condition:** revisit once adrpy has an install-level config
module; wire in the real two-stage fallback (repo pattern -> install-level
default -> generic "nothing found" if both are empty).
