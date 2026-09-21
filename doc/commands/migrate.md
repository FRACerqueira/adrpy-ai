<img src="../../src/adrpy/icon.png" width="160" alt="adrpy-ai icon">

[← Command Reference](INDEX.md)

# `adrpy migrate`

Adds an adrpy-compliant header to existing, hand-written decision files.

## Description

Adds an AdrPlus-compliant header to existing, hand-written decision files. Requires the repository's migrationpattern to be set, either directly (see the `config` command) or via the install-level config's own fallback (see the `installconfig` command); fails with migration-pattern-not-configured only when both are empty -- true for any freshly-init'd repository with no install-level config set up either. When the fallback supplies the value, it is also persisted back into this repository's own adr-config.adrplus -- inside the same repository lock as the rest of this command, but as an earlier, independent write, not atomically bundled with the migration itself: it commits before the scan/eligibility checks below run, and survives even if this same call goes on to fail one of them (migration-scan-failed/-incomplete/-unreliable-encoding, no-decisions-found, already-tool-created-adrs-exist, no-eligible-files-to-migrate) -- those refusals mean no DECISION file was touched, not that adr-config.adrplus itself wasn't. Subsequent commands see the persisted value directly, without consulting the install-level config again, regardless of whether this particular run went on to succeed. Best-effort per file: one file failing to write (e.g. a permission error) does not block the others. If any file fails, the whole command fails with migration-write-failed, whose `data.results` names every candidate file's own outcome (`migrated` or `failed`, with the error for the latter). A candidate whose title -- sourced from the raw legacy filename itself, unlike every other command's own title -- carries '|', a line-break-like character, a filesystem-unsafe character (`<>:"/\|?*` or a control character; the new header this write is about to build would otherwise embed it verbatim, or -- for the filesystem-unsafe set -- this file's own existing name already avoided them, since none of them survive as a real filename component on this platform), or consists entirely of whitespace/'_'/'-' (e.g. a legacy title segment of '---') -- the case-transform step falls back to echoing such a value raw, which can collide with the filename's own separator and produce a file the tool can never recognize again -- is one such per-file failure (field-contains-forbidden-character), never a silent write. If the repository lock is lost partway through (a different process reclaimed it), the whole run aborts immediately instead of continuing unprotected, with migration-lock-lost -- its own `data.results` names only the candidates actually attempted before the loss; none after. May instead fail with repository-locked if the lock could not be acquired in time before any file is touched, or with folderadr-changed-after-lock-acquired if a concurrent config change moved folderadr while this call was acquiring the lock -- no file is touched either way; retry. This is a one-time, largely irreversible operation for repositories with only manually-created decisions: refuses the ENTIRE run with already-tool-created-adrs-exist -- no decision file is touched -- if even ONE scanned file already has a valid, non-migrated header (i.e. this repository has decisions this tool itself already created). Refuses the whole run with migration-scan-unreliable-encoding, naming every affected file in `data.unreliable_files`, if any scanned file's content isn't valid UTF-8 -- a lossy decode there can't be trusted for the already-tool-created-adrs-exist safety check above or for candidate eligibility. Its structurally identical sibling, migration-scan-failed (`data.unreadable_file` names the one file), refuses the whole run the same way if a scanned file's header can't even be read (permission denied or similar) -- same scan phase, same all-or-nothing semantics, a real OSError instead of a lossy decode. Also refuses with migration-scan-incomplete (`data.unreadable` names the subdirectories) if a subdirectory under the decisions folder couldn't be scanned at all -- a hidden already-migrated file inside it could make the already-tool-created-adrs-exist check above silently answer 'no' when the true answer is 'yes'.

## Arguments

### `--path` / `-p` *(required, string)*

Repository root directory.

## Example

```bash
adrpy migrate --path .
```

---

This page is generated from the command's own `describe()` contract (the same JSON `adrpy help migrate` returns at runtime) -- if this page and the CLI ever disagree, the CLI is right and this page has drifted.
