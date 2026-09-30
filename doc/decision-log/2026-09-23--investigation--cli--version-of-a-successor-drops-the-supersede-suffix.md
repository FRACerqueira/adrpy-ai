# version on a supersede successor drops its --NNN suffix

Suspicion (Round 38 re-verification, informational): `version` on a successor ADR002--001 creates ADR0002V02 without the supersede suffix, so the new version no longer counts as a successor, and a reject on it would not revert the predecessor. This is adrpy's rule, not a defect: only the supersede itself carries the suffix. No code changed; the consequence (reject on a later version of a successor leaves the predecessor Superseded) stands.

Architectural review (Round 43): this is adrpy's own rule. The consequence recorded here stands.
