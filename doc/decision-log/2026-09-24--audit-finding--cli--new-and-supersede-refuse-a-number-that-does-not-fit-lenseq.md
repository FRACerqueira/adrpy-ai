# new and supersede refuse a number that does not fit lenseq; version and revise check the new number last

**Front:** Round 43: validator vs specification (independent oracle, Fable) | **Severity:** Medium | **Resolution:** Direct | **Round:** 43

With ADR999V01 and lenseq=3, new silently created ADR1000V01 (supersede likewise), while version/revise already had lenversion/lenrevision-too-small. New code lenseq-too-small-for-new-number with the same widening hint (adrpy config --lenseq N when it fits the maximum). version/revise now check the new number after refdate and fields, so all four commands check it last (the owner's D5 rule). Red/green. Fixed in c7331d0.
