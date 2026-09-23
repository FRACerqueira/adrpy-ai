<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy migrate`

Adds an adrpy-compliant header to existing, hand-written decision files.

## Description

Adds an AdrPlus-compliant header to existing, hand-written decision files. May fail with target-directory-not-found if --path does not point to an existing directory, or config-not-found if that directory has no adr-config.adrplus -- no file is touched either way. Requires the repository's migrationpattern to be set, either directly (see the `config` command) or via the install-level config's own fallback (see the `installconfig` command); fails with migration-pattern-not-configured only when both are empty -- true for any freshly-init'd repository with no install-level config set up either. When the fallback supplies the value, it is also persisted back into this repository's own adr-config.adrplus -- inside the same repository lock as the rest of this command, but as an earlier, independent write, not atomically bundled with the migration itself: it commits before the scan/eligibility checks below run, and survives even if this same call goes on to fail one of them (migration-scan-failed/-incomplete/-unreliable-encoding, no-decisions-found, already-tool-created-adrs-exist, no-eligible-files-to-migrate) -- those refusals mean no DECISION file was touched, not that adr-config.adrplus itself wasn't. Whenever that persist-back happened, the result -- success, any failure code this command reports, or interrupted -- carries migrationpattern_persisted with the pattern written (in data, on a failure); an unexpected internal-error does not. Subsequent commands see the persisted value directly, without consulting the install-level config again, regardless of whether this particular run went on to succeed. Best-effort per file: one file failing to write (e.g. a permission error) does not block the others. If any file fails, the whole command fails with migration-write-failed, whose `data.results` names every candidate file's own outcome (`migrated` or `failed`, with the error for the latter). A candidate whose title -- sourced from the raw legacy filename itself, unlike every other command's own title -- carries '|', a line-break-like character, a filesystem-unsafe character (`<>:"/\|?*` or a control character; the new header this write is about to build would otherwise embed it verbatim, or -- for the filesystem-unsafe set -- this file's own existing name already avoided them, since none of them survive as a real filename component on this platform), or consists entirely of whitespace/'_'/'-' (e.g. a legacy title segment of '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a file the tool can never recognize again -- is one such per-file failure (field-contains-forbidden-character), never a silent write. If the repository lock is lost partway through (a different process reclaimed it), the whole run aborts immediately instead of continuing unprotected, with migration-lock-lost -- its own `data.results` names only the candidates actually attempted before the loss; none after. May instead fail with repository-locked if the lock could not be acquired in time before any file is touched, or with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no file is touched either way; retry. This is a one-time, largely irreversible operation for repositories with only manually-created decisions: refuses the ENTIRE run with already-tool-created-adrs-exist -- no decision file is touched -- if even ONE scanned file already has a valid, non-migrated header (i.e. this repository has decisions this tool itself already created). Refuses the whole run with migration-scan-unreliable-encoding, naming every affected file in `data.unreliable_files`, if any scanned file's content isn't valid UTF-8 -- a lossy decode there can't be trusted for the already-tool-created-adrs-exist safety check above or for candidate eligibility. Its structurally identical sibling, migration-scan-failed (`data.unreadable_file` names the one file), refuses the whole run the same way if a scanned file's header can't even be read (permission denied or similar) -- same scan phase, same all-or-nothing semantics, a real OSError instead of a lossy decode. Also refuses with migration-scan-incomplete (`data.unreadable` names the subdirectories) if a subdirectory under the decisions folder couldn't be scanned at all -- a hidden already-migrated file inside it could make the already-tool-created-adrs-exist check above silently answer 'no' when the true answer is 'yes'.

## Arguments

### `--path` / `-p` *(required, string)*

Repository root directory.

## Failure codes

| Code | Condition |
|---|---|
| `target-directory-not-found` | --path does not point to an existing directory. |
| `config-not-found` | --path's own directory has no adr-config.adrplus. |
| `folderadr-changed-after-lock-acquired` | A concurrent config change moved folderadr while this call was acquiring the repository lock -- no file is touched either way; retry. |
| `migration-pattern-not-configured` | Both the repository's own migrationpattern and the install-level config's own fallback are empty. |
| `field-contains-forbidden-character` | A candidate's own title (sourced from its raw legacy filename) contains '\|', a line-break-like character, a filesystem-unsafe character, or consists entirely of whitespace/'_'/'-' -- a per-file failure, not a whole-batch abort. |
| `migration-scan-failed` | A candidate's own header could not even be read (permission denied or similar) -- refuses the whole run. |
| `migration-scan-incomplete` | A subdirectory under the decisions folder could not be scanned -- refuses the whole run. |
| `migration-scan-unreliable-encoding` | A scanned candidate's content isn't valid UTF-8 -- refuses the whole run. |
| `already-tool-created-adrs-exist` | At least one scanned file already has a valid, non-migrated header -- refuses the whole run. |
| `no-decisions-found` | No .md files matching a recognized naming scheme were found. |
| `no-eligible-files-to-migrate` | Every recognized file already has a header (migrated or tool-created) -- nothing needs migration. |
| `migration-lock-lost` | The repository lock was lost partway through -- data.results names only the candidates actually attempted before the loss. |
| `migration-write-failed` | At least one candidate failed to write -- data.results names every candidate's own outcome. |
| `path-invalid` | A resolved path is not usable (e.g. contains a NUL byte). |
| `path-outside-repository` | A resolved path escapes the repository boundary. |
| `io-error` | A write failed for a reason not covered by a more specific code (permission denied, full disk, etc.). |
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
adrpy migrate --path .
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help migrate` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
