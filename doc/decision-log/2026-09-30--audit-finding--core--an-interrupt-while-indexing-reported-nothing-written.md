# Ctrl+C while regenerating the index answered interrupted with no data after the writes had landed

**Front:** Resilience of the INDEX.md write path (round 50) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 50

Every call site runs after its write, outside any interrupt-reporting wrapper, so a Ctrl+C there reached __main__ and answered interrupted with no data, the shape the commands document for an interrupt before any write. The window now covers a full rescan.

Decided by the project owner between two options (a warning on the success, or interrupted with the data written): the result is the command's success, and the index not being updated is a warning. Red: test_an_interrupt_while_indexing_leaves_the_decision_written_and_says_so let KeyboardInterrupt escape and stopped pytest itself. Green after.
