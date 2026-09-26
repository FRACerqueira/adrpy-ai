# migrate is best-effort per file; AdrPlus 1.0.0 stops at the first failure

`cli/migrate.py`'s per-file loop now attempts every eligible candidate
regardless of an earlier failure, returning one `{"file", "status":
"migrated"|"failed", "error"}` entry per candidate. If any file failed,
the whole command still reports `success:false` with code
`migration-write-failed`, but `data.results` names every candidate's own
outcome deterministically — no inference required about which files were
never attempted.

**Why this diverges, and why it's safe to:** `MigrateCommandHandler.cs`'s
own per-file loop (`MigrateRepositoryAsync`) has no try/catch around its
per-file write either — a real I/O failure partway through propagates and
loses even the partial `result` list already built in that same run.
That is not a deliberate fail-fast design in the original, it's simply
the absence of any handling at all; there is no fidelity requirement
being broken by choosing differently. adrpy-ai's first attempt at
covering this gap (commit `4617990`) kept the loop fail-fast and added a
`migrated`/`failed_file` pair to `CommandError.data`, but that still
required the caller to infer, from a set difference against a candidate
list it never receives, which files were never attempted — and fail-fast
meant a single bad file (e.g. a transient permission error) blocked every
file after it in the same invocation. Best-effort per file is strictly
more useful to a non-interactive caller (an AI agent) that would
otherwise have to invoke `migrate` repeatedly just to make forward
progress past one bad file. `success:false` is kept as the top-level
signal on any failure specifically so `migrate` stays consistent with
every other command's own contract (the operation either fully succeeds
or reports a structured failure) rather than becoming the one command
that reports `success:true` with failures buried in a nested array.
Escalated and confirmed with the user (commit `550186f`).

Architectural review (Round 43): the behavior stays, with the reason restated now that adrpy is the reference and AdrPlus will mirror it, so it no longer rests on AdrPlus 1.0.0 lacking any handling. migrate runs once, before any decision is created, and is exempt from validate-before-acting. It prepares and commits each candidate on its own, an atomic write per file: a failure leaves the other candidates migrated and the failed one untouched, data.results names every outcome, and a re-run migrates only the files still without a header. A fallback migrationpattern is still persisted into adr-config.adrplus first, before any candidate, so a re-run finds it; that timing no longer has anything to do with the lock (ADR001).
