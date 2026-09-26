# When this skill applies

This is a heavyweight review process, not routine practice. It only
applies in one of these situations:

- Right before a release.
- When the project owner explicitly asks for a release-readiness or
  hardening review.
- At the start of a heavy rewrite.
- When a major version is approaching, or on the eve of a stable release.
- When a routine documentation-accuracy check (see below) turns up a real
  bug mid-pass, and the scope of what that implies is large enough to
  warrant a fuller look.

**A scoped ask needs a scope check before the full protocol runs.** The
second condition above ("explicitly asks for a release-readiness or
hardening review") carries no size or release-proximity qualifier on its
own, and a request that names only one module, one file, or one specific
concern -- with no release, version, or rewrite in view -- should not be
read as authorizing the full, multi-front heavyweight protocol by
default, even though it uses a trigger word like "hardening." Confirm
scope and depth first: does the project owner want the full multi-angle
pass, or a narrower, targeted review of just the area they named? Only
run the full protocol once that is confirmed; otherwise treat the request
as the lighter, targeted review it actually described. This is the same
proportionality the rest of this gate already protects -- a module-scoped,
pre-merge ask reads closer to the excluded "routine change / ordinary
feature work" case than to a real release-readiness moment.

Never run this as a background default for routine changes, bug fixes, or
ordinary feature work -- outside the moments above, it is expensive and
disproportionate to what the task actually needs. If none of the above
conditions is clearly true, don't invoke this skill -- say so, and continue
with the smaller task at hand instead.

A lighter, cheaper cousin does not need this gate: a documentation-only
pass -- checking docs against code -- is reasonable to run periodically as
its own routine check, not only as one-off release prep. Only the full,
heavyweight multi-angle protocol this skill describes requires the
conditions above; a plain doc-accuracy pass does not.
