# migrate is best-effort per file, unlike the real tool's implicit fail-fast

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
