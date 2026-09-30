# A failure other than OSError rebuilding the decision-log index answered interrupted or internal-error

**Front:** Resilience of the INDEX.md write path (round 51 confirmation) | **Severity:** Medium | **Resolution:** Direct | **Round:** 51

cli/log.py caught only OSError and CommandError around regenerate_index, the class round 50 fixed for the decisions index. An entry name holding a lone surrogate made a written entry answer interrupted, and the next identical call internal-error instead of log-entry-already-exists.

Fix: any Exception after the write is log-index-regeneration-failed naming the entry; on the collision path it is a warning on log-entry-already-exists. Ctrl+C still answers interrupted with the entry named. Red then green in tests/test_log.py. Accepted as Low (second opinion): Ctrl+C during the collision path's rebuild answers interrupted, nothing having been written.
