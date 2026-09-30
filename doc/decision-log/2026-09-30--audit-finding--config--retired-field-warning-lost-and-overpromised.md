# The retired-field warning was lost on some failures, promised removal at any write, and installconfig --seed kept the fields

**Front:** Compatibility of existing repositories and TUI contract passes (round 50) | **Severity:** Low | **Resolution:** Direct | **Round:** 50

__main__ merged the config-read notices into CommandError failures only: io-error, internal-error and interrupted lost them. The notice said the fields are removed at the next write, but lifecycle commands never rewrite the config, and installconfig --seed wrote the seed as given.

Fix: every failure branch carries the notices; the notice names config and installconfig as the writes that remove them; installconfig --seed re-serializes a seed that holds them (any other seed is still written as given, as test_seed_replaces_the_file_wholesale pins).

Red then green: tests in tests/test_config_command.py and tests/test_installconfig.py.
