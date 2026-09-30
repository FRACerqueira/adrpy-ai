# The retired-field warning was lost on a usage-error, promised a removal, and named no file

**Front:** Compatibility of existing repositories (round 51 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 51

init --language refused after reading an install-level config holding activeplugins, and the warning that read raised was dropped (emit_usage_failure took no warnings). The text promised removal at the next config write, even on the write that had just removed them, and never said which file held the fields: an install-level config or a --seed file looked like the repository's.

Fix: a usage-error carries the notices, with the same presence rule as every failure; the notice names the file and says to remove them from it; only a parse that knows its file raises it, so one text read twice gives one warning. Red then green in tests/test_config_command.py.
