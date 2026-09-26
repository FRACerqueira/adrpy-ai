# version on a supersede successor drops its --NNN suffix, as AdrPlus 1.0.0 also does

Suspicion (Round 38 re-verification, informational): `version` on a successor ADR002--001 creates ADR002V02 without the supersede suffix, so the new version no longer counts as a successor, and a reject on it would not revert the predecessor. Checked against the reference tool: AdrPlus's VersionCommandHandler.cs (lines 277-288) builds the new version's AdrRecord with no superseded field at all, so it drops the suffix the same way. AdrPlus's README does not address it either. This is fidelity to the reference behavior, not a defect adrpy introduced. No code changed; the consequence (reject on a later version of a successor leaves the predecessor Superseded) stays as the reference tool has it.

Architectural review (Round 43): adrpy is now the reference, so this is adrpy's own rule rather than fidelity to AdrPlus; AdrPlus 1.0.0 happens to behave the same. The consequence recorded here stands.
