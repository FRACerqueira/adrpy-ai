# Sibling test-coverage gaps found alongside the blank-content fix (untested domain/scope delimiter checks, CLI-integration seam, asymmetric empty-check breadth) are closed

**Front:** Test-Adequacy audit | **Severity:** Medium | **Resolution:** Direct | **Round:** 16

Round 16's Test-Adequacy pass, while mapping the blank-content bug's full boundary, found several sibling test-coverage gaps in the same neighborhood, closed alongside the production fix:

1. `new.py` never tested `field-contains-forbidden-character` for --domain/--scope at all, only --title, despite the identical call one line below.
2. `supersede.py` and `version.py` each tested the '|' rejection only for --scope, never --domain, despite `reject_embedded_delimiter(domain, "domain")` sitting one line below the tested --scope call in both files.
3. The 16 config header/status fields' forbidden-character/blank rejection was thoroughly tested at the schema layer (test_config.py), but never independently through the CLI command layer -- the CLI-to-schema integration seam itself was untested.
4. `test_empty_required_string_field_is_rejected` covered only `statusnew` for the literal-empty case, while its sibling pipe-rejection test is parametrized across all 16 fields -- an easy-to-miss asymmetry.

Also, `resolve_within`'s own blank-collapse behavior (later confirmed as the round's Critical finding) was first surfaced here as 'zero test coverage of any kind', before Stability turned it into a fully-reproduced live bug -- see the companion folderadr-collapse entry.

Fixed by adding: parametrized delimiter tests for new/supersede/version's domain/scope; a parametrized whitespace-only test across all 16 config header/status fields (matching the existing pipe test's own breadth); a CLI-layer integration test for config's header-field validation; and direct unit tests for `resolve_within`'s collapse-onto-base rejection and `reject_embedded_delimiter`'s blank/empty-string boundary (including the adversarial positive control: a literal empty string must keep succeeding, verified red on its own removal). Full suite (798 tests) green.
