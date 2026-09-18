# Contributing to adrpy-ai

Thanks for considering a contribution. This project has an unusually explicit process — read this before opening a pull request, it will save you a round trip.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Development Setup](#development-setup)
- [Running Tests](#running-tests)
- [The Project's Own Verification Discipline](#the-projects-own-verification-discipline)
- [Coding Guidelines](#coding-guidelines)
- [Architecture Decisions and the Decision Log](#architecture-decisions-and-the-decision-log)
- [Commit Messages](#commit-messages)
- [Submitting a Pull Request](#submitting-a-pull-request)
- [Reporting Bugs](#reporting-bugs)
- [Requesting Features](#requesting-features)

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md). Participation implies agreement with it.

## Development Setup

Requires Python 3.11+.

```bash
git clone https://github.com/FRACerqueira/adrpy-ai.git
cd adrpy-ai
pip install -e ".[dev]"
adrpy help
```

`adrpy-ai` has zero runtime dependencies by design (`dependencies = []` in `pyproject.toml`) — a pull request adding one is a significant decision on its own and should be discussed in an issue first, not just implemented.

## Running Tests

```bash
pytest
```

At the time of writing this suite has 650+ tests. A handful are platform-specific and will `skip` (not fail) on the wrong host — for example, tests exercising real POSIX symlinks skip on Windows, and vice versa for Windows junctions. That's expected; a skip is not a failure.

## The Project's Own Verification Discipline

This project follows a strict red-then-green protocol for every bug fix, and success-criteria-first testing for every new behavior:

1. **Bug fixes**: write a test that reproduces the bug, confirm it fails *for the reason you believe it does* (not a typo, not an unrelated error), then fix it, and confirm the same test passes plus the rest of the suite still does.
2. **New behavior**: write the test for the new behavior before or alongside the implementation, not after.
3. **A finding that turns out not to be a bug** still becomes a permanent test with a comment explaining why the suspected failure doesn't materialize — this stops the same suspicion from being re-investigated later by someone (or some agent) with no memory of this decision.

Pull requests that add behavior with no corresponding test, or that fix a bug with no test proving it's actually fixed, will be asked to add one before merge.

## Coding Guidelines

- **Simplicity first.** No abstraction for single-use code, no speculative configurability, no error handling for scenarios that can't happen.
- **Surgical changes.** A pull request should touch only what its own stated purpose requires — no drive-by formatting or unrelated refactors bundled in.
- **Match existing style**, even where you'd personally choose differently.
- **Every changed line should trace back to the request that caused it.** If you notice unrelated dead code or a real but unrelated problem while working, mention it in the PR description instead of fixing it in the same diff.

## Architecture Decisions and the Decision Log

This project records two different kinds of durable record, and dogfoods its own tool to write the first kind:

- **[`doc/adr/`](doc/adr/)** — formal Architecture Decision Records for genuinely architectural choices (a new dependency, a structural or cross-cutting design decision). Written using `adrpy` itself.
- **[`doc/decision-log/`](doc/decision-log/INDEX.md)** — a lighter-weight log for audit findings, confirmed divergences from the reference tool's behavior, deferred work with a named reopening condition, and accepted trade-offs. Write an entry with [`adrpy log`](doc/commands/log.md), which also regenerates `INDEX.md` as part of the same write ([ADR003V01](doc/adr/ADR003V01-decision-log-entries-separate-human-reviewed-judgment-from-tool-executed-mechanics-via-a-future-adrpy-log-command.md)) — `scripts/generate_decision_log_index.py` remains for regenerating the index alone, e.g. after an entry written by hand. `INDEX.md` itself is always generated, never hand-edited; individual entries are also never edited after being written — a correction is a new entry, not an edit to the old one.

See **[Writing a decision-log entry](doc/decision-log-workflow.md)** for the full step-by-step workflow, including which of the two this is for a given change and a diagram of the classification decision tree.

If your pull request makes a real architectural choice or a deliberate divergence from the reference tool's own confirmed behavior, please open an issue to discuss it before implementing — these get recorded, and recording a decision after the fact is a worse process than agreeing on it first.

## Commit Messages

Focus on *why*, not just *what*. "Fix lock ordering in migrate" says less than a message explaining what could go wrong without the fix. Reference the specific behavior or finding being addressed.

## Submitting a Pull Request

1. Fork the repository and create a branch from `main`.
2. Make your change, following the guidelines above.
3. Run `pytest` and confirm everything passes (skips are fine, failures aren't).
4. Open a pull request describing what changed and why. Link any related issue.
5. Be responsive to review feedback — this project prefers a few rounds of small, focused changes over one large diff that's hard to review.

## Reporting Bugs

Open an issue with: what you ran, what you expected, what actually happened (including the exact JSON response, if any), and your Python version and OS. If you can reduce it to a minimal repository/command sequence, that speeds things up considerably.

## Requesting Features

Open an issue describing the use case, not just the feature — this project ports the reference tool's own behavior deliberately and selectively (see [Relationship to AdrPlus](README.md#relationship-to-adrplus)), so understanding *why* you need something helps decide whether it belongs here or is better left out.
