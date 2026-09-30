# init over decisions named with other widths switched to the config's widths without a warning

**Front:** Compatibility of existing repositories (round 50) | **Severity:** Low | **Resolution:** Escalated | **Round:** 50

init checked that existing numbers fit the sizes, not that their widths match: over ADR001V01 files it wrote a 4/2/2 config, and new then named ADR0003V01R01 next to them.

Decided by the project owner (warn, or accept): init warns, naming up to three such files and saying to set the sizes with config before the next new decision. Legacy names are not counted.

Red then green in tests/test_init.py, with a same-width repository and a legacy name as the control.
