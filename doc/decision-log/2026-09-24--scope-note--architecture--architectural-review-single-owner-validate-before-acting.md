# Architectural review (Round 43): one owner per working copy, validate before acting, adrpy as the reference; obsolete log entries removed

Round 43 is the architectural review that followed Round 42. It changed three premises, decided by the project owner:

1. **Validate before acting.** Every lifecycle action (`new`, `approve`, `reject`, `undo`, `supersede`, `version`, `revise`) validates the whole repository first (`core/consistency.py`) and, when anything is broken, stops with `repository-inconsistent`, listing every error with a repair hint. `config` validates when it changes a guarded field (tolerating a file with no header); `explore`, `help`, `init`, `migrate` and `log` are exempt; `adrpy check` runs the validation alone. A `.md` whose name is not an ADR name is ignored. A multi-file write that stops halfway is repaired by hand (`multi-file-write-partially-applied` with data.applied, data.pending and data.repair); there is no `--resume`.
2. **No concurrency control.** One owner per working copy; git coordinates people; the last command to write a file wins. The atomic write per file, exclusive create and the orphan `.tmp` sweep remain. The rule is documented in the README, `doc/architecture.md`, `doc/skills/README.md` and the shipped decision-log skill.
3. **adrpy is the reference.** AdrPlus will mirror it. adrpy still reads AdrPlus 1.0.0 repositories (label-only status cells, the `<!-- Migrated -->` marker); a state AdrPlus can leave that breaks an invariant is refused with a hint, a one-time repair when adopting adrpy.

**The owner's one-time exception, valid only for this review:** ADRs rewritten in place instead of superseded, decision-log entries that lost their meaning removed, others adjusted in place, this one scope-note listing what was removed, and `CYCLES.md` recalculated. After this entry the normal rules apply again: entries are written once, and a correction is a new entry.

**ADRs rewritten in place** (status cells unchanged): ADR001V01 is now the single-owner model (renamed to `ADR001V01-single-owner-working-copy-without-concurrency-control,-validating-the-whole-repository-before-every-lifecycle-action.md`, with the measured cost and the visibility plan for a lost update that ends in a valid state); ADR006V01 no longer names the lock (renamed to `ADR006V01-decision-body-reads-and-writes-stream-chunk-by-chunk-instead-of-loading-whole-file-content-into-memory.md`); ADR002V01 and ADR007V01 lost their lock text; ADR002V01, ADR004V02 and ADR007V01 lost the parity framing; ADR004V02 gained a Round 43 section (AdrPlus 1.0.0 reading, the closed status set, non-ADR names ignored, `validate_config_change`); ADR005V01 gained a one-line note on the codes it lost.

**Removed: 21 entries.**

The repository lock and concurrency between adrpy processes (16), meaningless without a lock:
- 2026-09-16--audit-finding--lock--folderadr-freshness-validated-after-every-lock-acquire.md
- 2026-09-16--audit-finding--lock--lock-lost-bypassed-second-write-partial-mutation-reporting.md
- 2026-09-16--audit-finding--lock--reclaim-if-abandoned-tolerates-persistent-permission-error.md
- 2026-09-16--audit-finding--lock--release-path-read-failure-could-leak-or-mask.md
- 2026-09-16--audit-finding--lock--release-path-toctou-narrowed.md
- 2026-09-16--audit-finding--lock--second-corroboration-pass-confirms-migrate-and-config-lock-gaps.md
- 2026-09-16--audit-finding--lock--try-create-and-reclaim-stat-now-retry-permission-error.md
- 2026-09-16--audit-finding--lock--verify-still-held-treats-a-read-failure-as-lock-lost.md
- 2026-09-17--audit-finding--lock--reclaim-if-abandoned-second-call-site-tested-independently.md
- 2026-09-16--doc-drift--lock--init-table-no-longer-reflects-the-seed-on-existing-repo-fix.md
- 2026-09-16--investigation--lock--revise-and-migrate-pre-lock-config-gate-race-does-not-corrupt.md
- 2026-09-16--investigation--naming--stale-lenseq-does-not-corrupt-recognition.md (its regression test, `tests/test_naming.py::test_parse_any_filename_recognizes_a_file_built_under_a_different_lenseq`, stays)
- 2026-09-16--audit-finding--cli--repository-locked-lock-lost-documented-in-describe.md
- 2026-09-23--audit-finding--cli--migrate-lock-lost-reports-the-persisted-pattern.md
- 2026-09-23--audit-finding--cli--reject-lock-lost-between-writes-reports-the-revert.md
- 2026-09-22--deferred--skills--no-lock-on-agentsmd-writes.md -- its content is now the general rule: adrpy-skills, like adrpy, runs one command at a time on a working copy, with no lock (ADR001V01, `doc/skills/README.md`). Its reopening trigger no longer applies.

Tolerating invalid files, resuming, and hand-made states (5), replaced by validate-before-acting and a manual repair:
- 2026-09-23--risk-accepted--lifecycle--invalid-files-are-left-out-of-family-rules.md -- an invalid file is no longer left out of the family rules; it makes the repository inconsistent.
- 2026-09-23--retraction--lifecycle--lossy-sibling-fail-closed-and-damaged-migrated-member-dropped.md -- retracted under the rule above, now gone; the round-25 entry it retracted carries a note with the current rule.
- 2026-09-23--risk-accepted--cli--round-41-accepted-residuals.md -- both residuals concerned `supersede --resume` and hand-made successors, now validator errors.
- 2026-09-23--audit-finding--cli--supersede-resume-requires-explicit-flag-never-guesses.md -- `--resume` no longer exists.
- 2026-09-23--audit-finding--cli--supersede-resume-adopts-a-migrated-chain.md -- same; `2026-09-23--retraction--cli--migrated-supersede-chains-are-no-longer-adopted.md` keeps only its migrate refusal (`migration-successor-files-exist`).

**Adjusted in place: 34 entries.** Each ends with a paragraph starting "Architectural review (Round 43):" stating what still holds (search for that string); a few also lost a sentence about the lock or had their heading reworded, and none had its structured line changed. They are the entries that named the lock, `--resume` or the removed recovery codes as current (the round-25 and round-31 security entries, the supersede/reject write-order and recovery entries, the multi-write scope-note, the ADR005 registry scope-note, the retry and orphan-sweep entries, the Round 40 residuals and the Round 41 refusal-message entry), and every `accepted-divergence` entry plus `2026-09-23--investigation--cli--version-of-a-successor-drops-the-supersede-suffix-like-adrplus.md`, reframed from "divergence from AdrPlus" to "adrpy's behavior, which AdrPlus will mirror". The migrate best-effort entry keeps its behavior with the reason rewritten.

**Round 42, absorbed.** Its four fronts (state space with an EXIT invariant, docs vs code, release readiness, mutation testing) found no tool-only safety or liveness violation; every remaining state-space finding needed a hand-made file. V1-V4 are absorbed by the review: the validator refuses those states (its family invariants close V2 and V3), and V4's migrate part is carried into the review's re-triage. D1-D4 lost their meaning with the lock and `--resume`. The docs, release and mutation findings whose targets still exist are re-triaged in the review's last phase; the release items D7 (README links), D9 ("Round N" jargon in shipped text) and D10 (a leaked local path) stay with the owner.

**Also closed:** `2026-09-18--deferred--security--posix-symlink-escape-coverage-for-resolve-within.md`. A real POSIX symlink escape test exists (`tests/test_security.py::test_resolve_within_rejects_a_path_that_escapes_via_a_real_posix_symlink`, added in round 28) and runs on the ubuntu and macOS CI jobs; exclusive create's `os.link` branch is tested on every host (`tests/test_exclusive_create.py`). Not run on a POSIX host from this Windows session.

**Deliberately left out of the review:**
- `renumber`, until a real merge needs it (the `duplicate-number` hint covers the manual repair);
- `--no-validate` or `--force` on lifecycle actions;
- `check --fix`;
- a validation cache;
- calling git;
- the skills install manifest, the right fix for the "ownership proved by text" class but orthogonal to these premises, left for a later cycle;
- the radical config rule (no guarded field changes while any decision exists), left with the owner;
- splitting `lifecycle.py` into modules, which, if done, will be a separate mechanical commit.

`--round` is not accepted for a scope-note, so this entry carries no Round; `CYCLES.md` counts the review as Round 43 and closes the 40-42 cycle with a pointer to this entry.
