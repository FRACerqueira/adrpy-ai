# ADR-name and config-guard docs: .MD, a suffix without a title, unguarded lenseq, init does not validate

**Front:** Round 44: ADR-name and config-guard boundary (Fable oracle) | **Severity:** Low | **Resolution:** Direct | **Round:** 44

The independent spec oracle found no code divergence over 14k operations and five doc gaps, fixed in lifecycle.md, config.md, init.md and the README: .md is compared case-insensitively where the scan sees the file; ADR002V01--001.md is not an ADR name (the suffix needs a title); lenseq/lenversion/lenrevision have no guard in config (the next new fails with lenseq-too-small-for-new-number); init, with or without --seed, does not run check's validation; the migrationpattern guard text follows the new rule (8735a28).
