# Plugins/sync extensibility is now risk-accepted indefinitely, not deferred

This retracts `2026-09-15--deferred--plugins--sync-and-plugins-out-of-scope.md`'s own classification, not its reasoning: the decision to leave plugins/sync unported still stands, unchanged.

That entry named a concrete reopening condition ("a second real Python consumer of this extensibility need appears") and was classified `deferred` on that basis, per the decision-log skill's own operational test (a named, concrete condition -> `deferred`; no condition worth tracking -> `risk-accepted`). The project owner has since confirmed this is being postponed indefinitely, with no active expectation of that condition being tracked or revisited -- which is, by the skill's own test, `risk-accepted`, not `deferred`.

**No reopening condition is named going forward.** If a second real Python consumer of this extensibility ever does appear, that is new information at that point, not something being watched for -- it would be its own fresh decision, not a scheduled revisit of this one.
