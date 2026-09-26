# doc/commands/reject.md still described reject's old write order; regenerated from describe()

**Front:** Round 38: doc-drift front | **Severity:** High | **Resolution:** Direct | **Round:** 38

doc/commands/reject.md had not been regenerated since c95de39, before b96eb01 reversed reject's write order (2026-09-22--retraction--cli--reject-write-order-reverted-predecessor-first.md). It still said predecessor-revert failures leave this decision's own status already Rejected, and that a lock lost before the second write surfaces as reject-predecessor-write-failed. It also lacked reject-own-write-failed-after-predecessor-reverted. Nothing had recorded this as deferred, so it was a miss. Regenerated from the live describe() in 61e4d64, and again in 78938e4 for the new recovery text.
