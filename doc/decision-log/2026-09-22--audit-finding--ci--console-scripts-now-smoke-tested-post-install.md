# ci.yml and publish.yml now install the real package and invoke both console scripts

**Front:** Round 34: release-readiness front | **Severity:** Medium | **Resolution:** Direct | **Round:** 34

Round 34's release-readiness front found nothing in ci.yml or publish.yml ever installed the real package and invoked either console script -- pytest only ever imports adrpy.skills.__main__ in-process, never runs the actual adrpy-skills binary; publish.yml's build job builds the sdist/wheel and uploads them but never installs or invokes anything. This blind spot was live, not hypothetical: this repo's own long-lived dev .venv had adrpy.exe but no adrpy-skills.exe -- it predated that entry point being added to [project.scripts] and was never reinstalled, reproduced and confirmed locally (adrpy-skills --version failed with 'No such file or directory' until Obtaining file:///C:/Sources/adrpy-ai
  Installing build dependencies: started
  Installing build dependencies: finished with status 'done'
  Checking if build backend supports build_editable: started
  Checking if build backend supports build_editable: finished with status 'done'
  Getting requirements to build editable: started
  Getting requirements to build editable: finished with status 'done'
  Installing backend dependencies: started
  Installing backend dependencies: finished with status 'done'
  Preparing editable metadata (pyproject.toml): started
  Preparing editable metadata (pyproject.toml): finished with status 'done'
Building wheels for collected packages: adrpy-ai
  Building editable for adrpy-ai (pyproject.toml): started
  Building editable for adrpy-ai (pyproject.toml): finished with status 'done'
  Created wheel for adrpy-ai: filename=adrpy_ai-0.1.dev226+g6b997e1cd.d20260922-py3-none-any.whl size=8055 sha256=a686f03a23fe987a3b59b0beee1d77125074f77f3f6e798584b72b5bbcc7318c
  Stored in directory: C:\Users\Samsung\AppData\Local\Temp\pip-ephem-wheel-cache-_e922caz\wheels\ae\ea\57\0b8f500fd92670e0dcbbb3d3cf584538ee398e5416a2e1ce2d
Successfully built adrpy-ai
Installing collected packages: adrpy-ai
  Attempting uninstall: adrpy-ai
    Found existing installation: adrpy-ai 0.2.0
    Uninstalling adrpy-ai-0.2.0:
      Successfully uninstalled adrpy-ai-0.2.0
Successfully installed adrpy-ai-0.1.dev226+g6b997e1cd.d20260922 was re-run). Fixed: ci.yml runs adrpy-ai 0.1.dev226+g6b997e1cd.d20260922
ADR lifecycle CLI for humans and AI agents alike -- JSON-only, no wizard, zero dependencies.

Docs: https://github.com/FRACerqueira/adrpy-ai#readme
Decision-log workflow: https://github.com/FRACerqueira/adrpy-ai/blob/main/doc/decision-log-workflow.md
Usage: adrpy help / adrpy-skills 0.1.dev226+g6b997e1cd.d20260922
Multi-provider AI-coding-agent skills installer for adrpy-ai.

Usage: adrpy-skills help after the editable install, across the full OS/Python matrix, so a broken or missing entry point fails the same build that would otherwise pass on test discovery alone. publish.yml's build job additionally installs the actual built wheel (not editable) into a clean venv and runs the same two commands -- the one artifact that actually ships, now verified end to end before it's ever uploaded to TestPyPI/PyPI.
