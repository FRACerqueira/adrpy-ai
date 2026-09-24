<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy init`

Initializes an ADR repository: writes `adr-config.adrplus` and creates the decisions folder.

## Description

Initializes an ADR repository: writes adr-config.adrplus and creates the ADR folder. May fail with target-directory-not-found if --path does not point to an existing directory -- no write is attempted. Fails with config-already-exists if adr-config.adrplus is already there and no --seed was given -- use `config` to edit an existing repository's settings instead, or pass --seed to overwrite it outright. With no --seed and no --language, seeds from the install-level config (see the installconfig command; ADR002V01) if one has been set up on this machine, or from the built-in default otherwise -- the install-level config not existing is the normal state for any installation that has never run installconfig, not an error; the result's own `warnings` names this and points at `installconfig` when it happens, since it is the one case where nothing informed this repository's own settings at all. Not safe to call concurrently on a FRESH --path with no config yet (deliberately, see doc/adr/ADR001V01-...): two simultaneous first-time calls can silently overwrite one another's config, both reporting success -- callers must ensure at most one first-time init runs per fresh repository path at a time. --seed overwriting an ALREADY-existing repository's config is, by contrast, protected by the same repository lock every other write command uses. May fail with init-existing-numbers-scan-incomplete if a subdirectory under the decisions folder could not be scanned (permission denied or similar) -- the existing max number/version/revision, which lenseq/lenversion/lenrevision must fit, can't be trusted from an incomplete scan. Unlike every other failure documented on the --seed argument below, this one is NOT scoped to the already-existing-repository path -- it can also fire on a genuinely fresh `init` if a decisions folder with an unreadable subdirectory already exists under the target path. Once that scan itself succeeds, may also fail with lenseq-too-small-for-existing-decisions/lenversion-too-small-for-existing-decisions/lenrevision-too-small-for-existing-decisions (each names the offending existing number and the configured length in `data`) if the resulting lenseq/lenversion/lenrevision is too narrow for a decision that already exists on disk -- same scoping as the scan-incomplete check above (can fire on a genuinely fresh `init` too, not just --seed on an existing repository).

## Arguments

### `--path` / `-p` *(required, string)*

Target repository root directory (must already exist).

### `--seed` / `-s` *(optional, string)*

Path to a config JSON to seed the repository with, instead of the install-level config (see the installconfig command) or the built-in default. Fails with config-file-not-found if this path itself does not point to an existing file. Unlike a bare `init` on a fresh path, this OVERWRITES an already-existing adr-config.adrplus outright -- config-already-exists is not raised when --seed is given. The existing file must still parse (its folderadr locates the lock and scopes the change guards): a corrupted one fails with its own config-* code -- repair or remove it first. If the seed's own folderadr differs from the current one AND the OLD folder already has recognized decisions, fails with folderadr-change-blocked-by-existing-decisions instead of silently orphaning them (same rule as the `config` command's own --folderadr guard); if that check itself can't be completed (a subdirectory couldn't be scanned), fails closed instead with folderadr-change-scan-incomplete rather than assuming nothing was there. The NEW folder is checked too (same rule as `config`'s own guard): if it already exists and holds a file that would newly parse as a decision under the resulting config, fails with folderadr-change-would-adopt-unrelated-files (data.adopted_files lists the file paths) instead of silently absorbing it and corrupting next-number allocation -- the same scan-incomplete code above covers an unreadable subdirectory under the new folder too; skipped entirely when the new folder does not exist yet. The seed's own folderlog (ADR007V01) gets the same treatment: folderlog-change-blocked-by-existing-entries / folderlog-change-would-adopt-unrelated-files / log-scan-incomplete, same rule as the `config` command's own --folderlog guard. Likewise, if the seed's own statusnew/statusacc/statusrej/statussup/separator/migrationpattern differ from the current ones in a way that would break recognition of an existing decision, fails with status-or-separator-change-blocked-by-existing-decisions (ADR004V01/V02; same rule as the `config` command's own guard for these fields -- status labels and --separator block on any recognized decision (--separator's recognition dependency is current-scheme-only, but a value already present in a legacy filename could silently reclassify it under the current-scheme parser, so it cannot be scoped the way --migrationpattern safely can); --migrationpattern blocks only if a LEGACY-scheme decision exists. This is a PERMANENT block once the decisions it actually protects exist, with no migration path -- for the four status fields and --separator that means ANY recognized decision, any scheme (the ADR004V01 marker future-proofs RECOGNITION of files that already carry it against a later label change, but does not exempt THIS GUARD from refusing the config change itself -- a marker-protected repository is blocked exactly the same as one with none); for --migrationpattern it means a LEGACY-scheme decision specifically. data.changed_fields on this error names only the field(s) actually blocking, not necessarily every field the seed touched) -- or status-or-separator-change-scan-incomplete if that check itself can't be completed (that sibling error's own data.changed_fields DOES list every guarded field touched, since it fails closed unconditionally). If the seed's own separator would make a file NOT currently recognized as a decision (by either scheme) newly parse as one, fails instead with separator-change-would-adopt-unrelated-files (data.adopted_files lists the file paths) -- unlike migrationpattern, which is deliberately allowed to newly recognize pre-existing legacy files as its own documented purpose, separator has no intentional-adoption use case, so any file it would newly sweep in is treated as an unintended side effect and blocked. This check only ever runs once the blocked-by-existing-decisions check above has already passed, so it only ever fires when zero existing decisions are at risk -- those two outcomes are mutually exclusive by construction, never coexisting. This guard's own scan-incomplete check runs BEFORE this command's own init-existing-numbers-scan-incomplete check below, so when both an unreadable subdirectory and a guarded field change occur together, status-or-separator-change-scan-incomplete is what's raised (unless the seed also changes folderadr, whose own folderadr-change-scan-incomplete fires first). On this same already-existing-repository path, may also fail with repository-locked, lock-lost, or folderadr-changed-after-lock-acquired (a concurrent config change moved folderadr while this call was acquiring the lock -- retry) -- never on a genuinely fresh path, which takes no lock at all. See this command's own top-level description for init-existing-numbers-scan-incomplete, which is NOT scoped to this --seed path either.

### `--language` *(optional, string)*

Built-in default language pack for header/status labels and the default template (one of ('en-us', 'pt-br', 'de-de', 'es-es', 'fr-fr', 'it-it', 'ja-jp', 'ko-kr', 'nl-be', 'ru-ru', 'zh-cn')); cannot be combined with --seed, and cannot be used when an install-level config exists on this machine (both --seed and the install-level config are full content sources; the caller must pick one explicitly rather than have one silently win) -- fails with usage-error either way. Defaults to en-us when neither --seed nor an install-level config apply.

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory. |
| `config-already-exists` | adr-config.adrplus already exists and no --seed was given. |
| `config-file-not-found` | --seed does not point to an existing file. |
| `language-not-supported` | --language is not one of SUPPORTED_LANGUAGES. |
| `folderadr-changed-after-lock-acquired` | A concurrent config change moved folderadr while --seed was acquiring the repository lock -- no write was made; retry. |
| `folderadr-change-blocked-by-existing-decisions` | --seed's own folderadr differs from the current one, and the OLD folder already has recognized decisions. |
| `folderadr-change-scan-incomplete` | A subdirectory under the OLD or NEW folderadr could not be scanned while checking --seed's own folderadr change. |
| `folderadr-change-would-adopt-unrelated-files` | The NEW folderadr already holds a file that would newly parse as a decision. |
| `folderadr-folderlog-alias-same-directory` | folderadr and folderlog resolve to the same real directory (or one nested inside the other), typically via a symlink or junction. |
| `folderlog-change-blocked-by-existing-entries` | --seed's own folderlog differs from the current one, and the OLD directory already has decision-log entries. |
| `folderlog-change-would-adopt-unrelated-files` | The NEW folderlog already holds a file that would newly parse as a decision-log entry. |
| `log-directory-contains-unrecognized-file` | The OLD or NEW folderlog contains a .md file that does not parse as a valid decision-log entry. |
| `log-scan-incomplete` | A subdirectory under the OLD or NEW folderlog could not be scanned while checking --seed's own folderlog change. |
| `status-or-separator-change-blocked-by-existing-decisions` | --seed's own status-label/separator/migrationpattern would break recognition of an existing decision. |
| `status-or-separator-change-scan-incomplete` | A subdirectory under the OLD folderadr could not be scanned while checking a guarded field change. |
| `separator-change-would-adopt-unrelated-files` | --seed's own separator would make a file NOT currently recognized as a decision newly parse as one. |
| `init-existing-numbers-scan-incomplete` | A subdirectory under the decisions folder could not be scanned while computing the existing max number/version/revision. |
| `lenseq-too-small-for-existing-decisions` | The resulting lenseq is too narrow for a decision number that already exists on disk. |
| `lenversion-too-small-for-existing-decisions` | The resulting lenversion is too narrow for a decision version that already exists on disk. |
| `lenrevision-too-small-for-existing-decisions` | The resulting lenrevision is too narrow for a decision revision that already exists on disk. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `io-error` | The write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |
| `config-file-too-large` | The config file exceeds the 64KB size limit. |
| `config-invalid-encoding` | The config file's bytes are not valid UTF-8. |
| `config-invalid-json` | The config file is not valid JSON, or its root is not a JSON object. |
| `config-missing-field` | The config is missing one or more required fields. |
| `config-unexpected-field` | The config has one or more fields this schema does not recognize. |
| `config-wrong-type` | A field's value is not the type this schema requires for it (string/integer/boolean/array of strings). |
| `config-lenseq-too-small` | lenseq is below its configured minimum (3). |
| `config-lenseq-too-large` | lenseq is above its configured maximum (6). |
| `config-lenversion-too-small` | lenversion is below its configured minimum (2). |
| `config-lenversion-too-large` | lenversion is above its configured maximum (4). |
| `config-lenrevision-negative` | lenrevision is below its configured minimum (0). |
| `config-lenrevision-too-large` | lenrevision is above its configured maximum (3). |
| `config-separator-invalid` | separator is not one of ('-', '_', '.'). |
| `config-casetransform-invalid` | casetransform is not one of the recognized case-transform names. |
| `config-field-empty` | A field that must be non-empty is an empty string. |
| `config-prefix-invalid` | prefix is not ASCII letters only, max 5 characters. |
| `config-folderadr-too-long` | folderadr exceeds 50 characters. |
| `config-folderadr-not-relative` | folderadr is absolute, drive-relative, or a UNC path -- it must be relative to the repository. |
| `config-folderlog-too-long` | folderlog exceeds 50 characters. |
| `config-folderlog-not-relative` | folderlog is absolute, drive-relative, or a UNC path -- it must be relative to the repository. |
| `config-folderadr-folderlog-overlap` | folderadr and folderlog are the same directory, or one is nested inside the other. |
| `config-template-too-long` | template exceeds 10000 characters. |
| `config-headerdisclaimer-too-long` | headerdisclaimer exceeds 100 characters. |
| `config-field-is-blank` | A field is non-empty but blank after stripping whitespace. |
| `config-field-contains-forbidden-character` | A field contains '\|' or a line-break-like character (or, for the 4 status labels, '(', ')', '<!--', '-->', or ':'; or, for headertablefields/headertablevalues, '<!--' or '-->'). |
| `config-migrationpattern-invalid` | migrationpattern is non-empty but does not match N##:##T##[V##:##][R##:##][P##:##]. |
| `config-headertitlefile-too-long` | headertitlefile exceeds 40 characters. |
| `config-headerversion-too-long` | headerversion exceeds 40 characters. |
| `config-headerrevision-too-long` | headerrevision exceeds 40 characters. |
| `config-headerscope-too-long` | headerscope exceeds 40 characters. |
| `config-headerdomain-too-long` | headerdomain exceeds 40 characters. |
| `config-headertitlestatuscreated-too-long` | headertitlestatuscreated exceeds 40 characters. |
| `config-headertitlestatuschanged-too-long` | headertitlestatuschanged exceeds 40 characters. |
| `config-headertitlestatussuperseded-too-long` | headertitlestatussuperseded exceeds 40 characters. |
| `config-headertablefields-too-long` | headertablefields exceeds 40 characters. |
| `config-headertablevalues-too-long` | headertablevalues exceeds 40 characters. |
| `config-headermigrated-too-long` | headermigrated exceeds 40 characters. |
| `config-statusnew-too-long` | statusnew exceeds 25 characters. |
| `config-statusacc-too-long` | statusacc exceeds 25 characters. |
| `config-statusrej-too-long` | statusrej exceeds 25 characters. |
| `config-statussup-too-long` | statussup exceeds 25 characters. |
| `repository-locked` | The repository lock could not be acquired before timing out. |
| `lock-lost` | The repository lock was acquired but reclaimed by another process before this write could commit -- no write was made; retry. |

## Example

```bash
# Initialize a new repository, seeded from the built-in default
adrpy init --path .

# Initialize with a specific language pack
adrpy init --path . --language pt-br
```

---

This page mirrors the command's own `describe()` contract (the same JSON `adrpy help init` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
