# When this skill applies

Use it for any task that touches Architecture Decision Records (ADRs) or
other decision records in a repository that has an `adr-config.adrplus`
file at its root: creating, accepting, rejecting, versioning, revising,
superseding or migrating a decision, fixing a failing `adrpy check`, or
changing the repository's ADR configuration. The `adrpy` command must be
on `PATH` (it comes with `pip install adrpy-ai`).

It does not apply when the repository has no `adr-config.adrplus`: then
adrpy does not manage its decisions, unless the user asks to set it up
(`adrpy init --path .`).

This skill says how to change the decision files. Whether a decision
should be recorded at all, and when, is not decided here: if the
`decision-log` skill is installed, its approval gate applies before any
write.
