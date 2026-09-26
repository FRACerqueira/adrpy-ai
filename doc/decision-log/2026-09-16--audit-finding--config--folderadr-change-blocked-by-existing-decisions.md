# Changing folderadr is now blocked while decisions still exist under the old path

**Front:** Stability (round 5 re-run), Finding 5 | **Severity:** High | **Round:** 5

Round 5 stability re-run, Finding 5: letting `folderadr` change freely made every existing decision invisible at its old, still-real path. Confirmed with the user: a `folderadr` change is now only valid when the OLD folder has no recognized decisions yet; otherwise it fails with a structured `folderadr-change-blocked-by-existing-decisions` (`data.existing_decisions` names the count) instead of silently orphaning them. Applied to both `config --folderadr` and `init --seed` (the same risk exists on that path too, per the "close the class, not the instance" rule -- `core/lifecycle.reject_folderadr_change_if_decisions_exist`, shared by both). `config.py` also gained the previously-missing piece of this same finding: nothing created the NEW folder after an allowed change, matching `init`'s own mkdir-after-write precedent.

**Alternatives considered before this fix, for the record:** always auto-create the new folder without any gate (rejected -- doesn't address the orphaning, only the missing-directory symptom).

Architectural review (Round 43): the lock this finding also reasoned about is gone (ADR001), and the two sentences about it were taken out of this entry. The block itself stands; it now lives in `core/lifecycle.validate_config_change`, which replaced `reject_folderadr_change_if_decisions_exist`, and changing `folderadr` also validates the repository first.
