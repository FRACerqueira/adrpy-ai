# Decision log cycles

A **cycle** groups a range of `Round` numbers (see `INDEX.md`) under a
human-friendly name, for narrative/retrospective reference only. It is
never a field on individual decision-log entries -- only `Round` (a
single, project-wide, ever-increasing integer) lives there. This file is
the only place a cycle's name is ever recorded.

## The naming rule

1. **Derive the name from the cycle's own dominant theme**, grounded in
   the real content of its rounds (the `scope`/`Front` of its
   `audit-finding`/`doc-drift` entries, and any ADR born or touched
   during it) -- never from a sequence number alone. State which entries
   support the name, so it's checkable, not a guess.
2. **Name the outcome, not the process.** Test: could someone with zero
   context read the name and guess roughly what got safer/better? "Round
   1-10" or "Initial Audit Push" fail this test (they describe that a
   process happened). "Concurrency & Data-Integrity Hardening" passes
   (it says what changed).
3. **Short, and immutable once written here.** A correction is a new
   note pointing at the old one, never an edit in place -- same
   discipline as decision-log entries themselves. Since a cycle name
   lives in exactly one place (this file), a correction only ever touches
   one row, never a batch of entries.
4. **Named in hindsight, never planned in advance.** A cycle's own
   dominant theme isn't knowable until it's over -- naming one before it
   closes would mean guessing at content that doesn't exist yet.
5. **Closed by the same signal the `pre-release-audit` skill already
   uses to end an audit**: the project owner says it's done/paused, not
   a fixed round count or calendar cadence decided in advance. No second
   mechanism invented for this. If a new round is proposed after a long,
   ambiguous gap with no explicit close ever declared, ask whether it
   continues the current (still-open, unnamed) cycle or starts a new one
   -- never assume either way.
6. **Always proposed, never decided unilaterally by the agent** -- same
   "ask before writing" gate as every other decision-log write. A cycle
   can stay open and unnamed indefinitely; naming isn't mandatory until
   someone wants to reference the whole span as one thing.

## Cycles

| Rounds | Dates | Name | Notes |
|---|---|---|---|
| 1-10 | 2026-09-15 to 2026-09-18 | **Hardening de Concorrência e Integridade de Dados** | Closed (audit explicitly paused after round 10). Supporting evidence (rule 1): of the 12 High-severity `audit-finding` entries across this cycle, 8 are directly about concurrency/data-integrity -- lost updates and orphaned successors under concurrent access (`second-corroboration-pass-confirms-migrate-and-config-lock-gaps`, round 4), stale-config-after-lock races (`folderadr-freshness-validated-after-every-lock-acquire`, round 6), lock-loss misclassification (`verify-still-held-treats-a-read-failure-as-lock-lost`, round 6), family-guard corruption (`supersede-and-reject-family-guard-and-predecessor-selection-fixed`, round 7), an unsafe write-before-dependency-check ordering (`folderadr-new-folder-created-before-config-commits`, round 7, itself a `Retraction`), and unreadable-subdirectory-masked corruption (`fail-closed-on-unreadable-subdirectory-for-safety-decisions`, round 8, plus its two round-9 test-coverage follow-ups). This is also the cycle in which `doc/adr/ADR001V01-...md` (Domain: concurrency) was born. |
| 11 | 2026-09-18 | **Precisão de Contrato e Cobertura do Install-Config** | Closed (single-round cycle, explicitly closed and named by the project owner). Supporting evidence (rule 1): 12 `audit-finding` entries total, dominated by Usability (7, including all 3 of the round's Medium findings -- `install-config--bare-read-omitted-updated-fields-key`, `install-config--seed-plus-field-flag-misreports-updated-fields`, `migrate--no-file-is-touched-claim-was-false-after-persist-back`) and Test-Adequacy (3, all zero-prior-coverage branches closed via mutation-confirmed new tests -- `install-config--seed-schema-validation-had-zero-test-coverage`, `migrate--empty-fallback-pattern-branch-had-no-dedicated-test`, `tests--conftest-isolation-fixture-scope-undocumented`); 2 Stability findings were Low. Every Usability finding was the same shape: `describe()`/response-shape text not matching the real behavior of the install-level config module born in ADR002V01 -- including the one finding not scoped to that module at all (`init--default-repo-config-template-used-crlf-language-packs-use-lf`, a pre-existing "defaults to en-us" claim that wasn't literally true, found in passing by the same pass). Both of the round's Medium findings also carried an escalated behavior/design question, both resolved after this cycle's own rounds closed (`install-config--seed-plus-field-flag-now-raises-usage-error`, `migrate--persist-back-write-timing-confirmed-as-is`). |
