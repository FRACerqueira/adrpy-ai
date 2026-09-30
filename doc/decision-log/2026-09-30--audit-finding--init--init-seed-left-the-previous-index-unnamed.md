# init --seed changing folderadr left the previous folder's generated index unnamed

**Front:** Resilience of the INDEX.md write path (round 51 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 51

Only config named the previous folder's index after a folderadr change. Fix: adr_index.previous_index_warning, shared by config and init --seed. Red then green in tests/test_adr_index.py. Accepted as Low: a case-only change in a case-sensitive Windows folder is not seen as a change.
