# publish.yml could publish to real PyPI from any branch with no test verification -- now gated on tests passing and the tag being on main

**Front:** Manual security/resilience review of publish.yml (not a formal audit round) | **Severity:** High | **Resolution:** Direct | **Round:** 17

A targeted review of `.github/workflows/publish.yml` (not a formal audit round -- a direct request, since the package is not yet published) found two real gaps, both confirmed against the actual files rather than assumed:

1. **No test-passing gate before publish.** `ci.yml` only triggers on push/PR to `main`/`develop` -- confirmed live it never runs on a tag push. `publish.yml` triggers purely on `tags: ["v*"]`, with no dependency on the tagged commit's own tests having passed anywhere. A tag push could reach real PyPI with zero automated verification that the suite even passes.
2. **No branch restriction on the tag trigger.** `on: push: tags: ["v*"]` fires regardless of which branch/commit the tag points to. Confirmed live: HEAD was on `develop` (not `main`) with no tags yet, and nothing in the workflow would have refused a tag pushed from there.

Also verified, empirically, that the package itself is sound (not a finding, recorded for completeness): built sdist+wheel locally via `python -m build`, confirmed the wheel contains every resource file, installed it into a fresh venv, and confirmed `adrpy --version`/`adrpy help` both work end-to-end from the installed package.

Fixed by adding a `verify` job that `build` now depends on: runs `pytest -v`, then `git merge-base --is-ancestor "$GITHUB_SHA" origin/main`, refusing to proceed (`::error::` + exit 1) if the tagged commit is not reachable from `main`. Could not red/green this via a real GitHub Actions run -- that requires pushing an actual tag, out of scope while publishing stays on hold -- verified instead via local YAML validation and careful reading of the exact git/pytest commands used, each already standard, well-understood operations on their own.
