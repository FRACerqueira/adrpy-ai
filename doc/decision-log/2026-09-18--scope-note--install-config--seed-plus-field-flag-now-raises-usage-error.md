# Resolved: installconfig --seed + field flag now raises UsageError

Closes the open behavior question left by `2026-09-18--audit-finding--install-config--seed-plus-field-flag-misreports-updated-fields.md` (that entry's own doc fix stands; this resolves the design question it deliberately left open).

**Decision, confirmed by the project owner:** a field flag passed alongside `--seed` now raises `UsageError` (`--seed cannot be combined with field flags...`), matching `init`'s own precedent for its incompatible flag combination (`--seed`+`--language`). Previously the flag was silently ignored while still reported in `updated_fields` as if applied.

adrpy-ai `8472349`. `test_seed_does_not_merge_with_field_flags` (asserting the old silent-ignore behavior) replaced with `test_seed_combined_with_a_field_flag_raises_usage_error`; mutation-verified red (check disabled, `DID NOT RAISE UsageError`) then green.
