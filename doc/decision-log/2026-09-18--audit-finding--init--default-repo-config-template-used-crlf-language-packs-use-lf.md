# default_repo_config.json's template used CRLF, every language pack uses LF

**Front:** Usability | **Severity:** Low | **Resolution:** Direct | **Round:** 11

Found during round 11's usability pass (Round 11 scope-note: `2026-09-18--scope-note--install-config--round-11-audit-scope-stability-usability-test-adequacy.md`), while cross-checking `init`'s own `describe()` claim ("Defaults to en-us when neither --seed nor an install-level config apply") against the actual bundled resource files. Pre-existing since before this session -- neither `default_repo_config.json` nor any language pack was touched by ADR002V01's own work, only discovered while auditing it.

All 11 language packs under `src/adrpy/resources/language_packs/` (including `en-us.json`, the one init's own default is supposed to match) store their `template` field's line breaks as bare `\n`. `default_repo_config.json`'s own `template` field stored the same prose content with `\r\n` instead -- confirmed byte-identical after normalizing line endings, so this was purely a line-ending divergence, not a content difference. A bare `init` and an explicit `init --language en-us` therefore produced byte-different `adr-config.adrplus` files for what `describe()` claims is the same default.

**Fix:** normalized `default_repo_config.json`'s `template` field to bare `\n`, matching every language pack's own convention (adrpy-ai `776fc6a`). Added `test_bare_init_and_explicit_language_en_us_produce_byte_identical_template` (`tests/test_init.py`) to pin this down going forward -- red (CRLF vs LF mismatch), then green after the fix.
