# The first phase boundary let new run between two migrate runs and lock migrate out; the boundary is now where migrate stops running, and write commands warn about a possible number collision

**Front:** Round 45: independent review of the phase rule (ADR012) | **Severity:** High | **Resolution:** Escalated | **Round:** 45

The first implementation of ADR012 ended the adoption at any valid header, migrated ones included: after a partial migrate, the files left stopped blocking, new ran, and migrate refused for good (already-tool-created-adrs-exist). Owner decision: the adoption ends when a decision migrate did not write exists -- the same test migrate uses. The same review showed new could take an ignored file's number or title silently; owner decision: every lifecycle command carries the phase warning, which says the number may be taken (no reservation) (572c5c7).
