<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy init`

Initializes an ADR repository: writes `adr-config.adrplus` and creates the decisions folder.

## Description

Initializes an ADR repository: writes adr-config.adrplus and creates the ADR folder. With no --seed and no --language, seeds from the install-level config (see the installconfig command; ADR002V01) if one has been set up on this machine, or from the built-in default otherwise -- the install-level config not existing is the normal state for any installation that has never run installconfig, not an error; the result's own `warnings` names this and points at `installconfig` when it happens, since it is the one case where nothing informed this repository's own settings at all. Not safe to call concurrently on a FRESH --path with no config yet (deliberately, see doc/adr/ADR001V01-...): two simultaneous first-time calls can silently overwrite one another's config, both reporting success -- callers must ensure at most one first-time init runs per fresh repository path at a time. --seed overwriting an ALREADY-existing repository's config is, by contrast, protected by the same repository lock every other write command uses. May fail with init-existing-numbers-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- the existing max number/version/revision, which lenseq/lenversion/lenrevision must fit, can't be trusted from an incomplete scan. Unlike every other failure documented on the --seed argument below, this one is NOT scoped to the already-existing-repository path -- it can also fire on a genuinely fresh `init` if a decisions folder with an unreadable subdirectory already exists under the target path.

## Arguments

### `--path` / `-p` *(required, string)*

Target repository root directory (must already exist).

### `--seed` / `-s` *(optional, string)*

Path to a config JSON to seed the repository with, instead of the install-level config (see the installconfig command) or the built-in default. Unlike a bare `init` on a fresh path, this OVERWRITES an already-existing adr-config.adrplus outright -- config-already-exists is not raised when --seed is given. If the seed's own folderadr differs from the current one AND the OLD folder already has recognized decisions, fails with folderadr-change-blocked-by-existing-decisions instead of silently orphaning them (same rule as the `config` command's own --folderadr guard); if that check itself can't be completed (a subdirectory couldn't be scanned), fails closed instead with folderadr-change-scan-incomplete rather than assuming nothing was there. Likewise, if the seed's own statusnew/statusacc/statusrej/statussup/separator/migrationpattern differ from the current ones in a way that would break recognition of an existing decision, fails with status-or-separator-change-blocked-by-existing-decisions (ADR004V01/V02; same rule as the `config` command's own guard for these fields -- status labels block on any recognized decision, --separator only if a CURRENT-scheme decision exists, --migrationpattern only if a LEGACY-scheme decision exists, and for those last two this is a PERMANENT block once the scheme it governs has any decision, with no migration path) -- or status-or-separator-change-scan-incomplete if that check itself can't be completed. This guard's own scan-incomplete check runs BEFORE this command's own init-existing-numbers-scan-incomplete check below, so when both an unreadable subdirectory and a guarded field change occur together, status-or-separator-change-scan-incomplete is what's raised. On this same already-existing-repository path, may also fail with repository-locked, lock-lost (see this command's own top-level description), or folderadr-changed-after-lock-acquired (a concurrent config change moved folderadr while this call was acquiring the lock -- retry) -- never on a genuinely fresh path, which takes no lock at all. See this command's own top-level description for init-existing-numbers-scan-incomplete, which is NOT scoped to this --seed path either.

### `--language` *(optional, string)*

Built-in default language pack for header/status labels and the default template (one of ('en-us', 'pt-br', 'de-de', 'es-es', 'fr-fr', 'it-it', 'ja-jp', 'ko-kr', 'nl-be', 'ru-ru', 'zh-cn')); cannot be combined with --seed, and cannot be used when an install-level config exists on this machine (both --seed and the install-level config are full content sources; the caller must pick one explicitly rather than have one silently win) -- fails with usage-error either way. Defaults to en-us when neither --seed nor an install-level config apply.

## Example

```bash
# Initialize a new repository, seeded from the built-in default
adrpy init --path .

# Initialize with a specific language pack
adrpy init --path . --language pt-br
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help init` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
