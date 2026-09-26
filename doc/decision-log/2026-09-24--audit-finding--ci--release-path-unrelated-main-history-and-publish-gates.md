# origin/main shares no history with develop, private vulnerability reporting is off and no environment gates PyPI

**Front:** Round 43: release readiness | **Severity:** High | **Resolution:** Escalated | **Round:** 43

git merge-base origin/main develop is empty: GitHub's initial commit on main is unrelated to develop, so a PR or merge to main fails and force-push is blocked. A scratch clone showed --allow-unrelated-histories resolves with conflicts only in .gitignore and README (keep develop's), leaving the tree identical. SECURITY.md points to private vulnerability reporting, which is disabled; no testpypi/pypi environments exist, so any v* tag on main would publish unapproved. These three are owner actions at release time (checklist in the Round 43 release report). Fixed here: skip-existing on PyPI, Python 3.14 in CI and classifiers, sdist without .github and the decision log (c7331d0).
