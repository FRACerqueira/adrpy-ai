# Round 50's docs left a guarded-field sentence, a --001 suffix, stale links and a missing diagram

**Front:** Documentation versus code (round 51 confirmation) | **Severity:** Low | **Resolution:** Direct | **Round:** 51

init's describe() still listed the guarded fields without headertablefields in one sentence; lifecycle.md showed a --001 suffix; explore's texts said the generated INDEX.md is left out, where any INDEX.md at the folder's root is; CHANGELOG and architecture.md linked ADR0011 and ADR0012 R00, not R01; README and CONTRIBUTING promised a diagram the workflow page no longer has; architecture.md's rule for warnings on a failure and its check example were wrong; lifecycle.md and explore did not list the decision-shaped headered warning. Fixed, pages regenerated, the second opinion's runs and link check passing.
