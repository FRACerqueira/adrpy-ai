# version's scope/domain defaults and the refdate bound come from the target, not a rejected attempt

**Front:** Round 41: pre-commit re-verification | **Severity:** Low | **Resolution:** Escalated | **Round:** 41

K1a, decided by the owner, fixed in 8c2f673: branching off V01 while newer versions were rejected, version took scope/domain defaults and the --refdate lower bound from the family's latest member -- a rejected attempt. version now defaults scope/domain to the target's, and version/revise bound --refdate by the target's own dates.
