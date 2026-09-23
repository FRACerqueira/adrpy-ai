# adrpy-skills' own __main__.py now catches KeyboardInterrupt, like adrpy's

**Front:** Round 37: test-adequacy front | **Severity:** High | **Resolution:** Direct | **Round:** 37

Round 36 fixed KeyboardInterrupt at adrpy/__main__.py's CLI boundary (2026-09-22--audit-finding--core--main-catches-keyboardinterrupt.md), but the sibling entry point, adrpy/skills/__main__.py, never got the same fix: a Ctrl+C mid-install escaped the except Exception catch-all with empty stdout, breaking the JSON-contract guarantee. Fixed with the same except KeyboardInterrupt clause returning code 'interrupted' (ad6cebb), with a red/green test. Class closed by search: exactly 2 `def main(` entry points exist in src/, both now covered.
