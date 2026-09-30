# A migrate or supersede that fails part way leaves INDEX.md as it was until the next write

migration-write-failed and multi-file-write-partially-applied are raised before the index is regenerated, so the page misses what was written. Accepted by the owner: the failure is loud, the repository is already inconsistent until repaired, the hint's repair reruns the command, which regenerates the page, and ADR0013V01R02 promises the page at the end of a successful run.
