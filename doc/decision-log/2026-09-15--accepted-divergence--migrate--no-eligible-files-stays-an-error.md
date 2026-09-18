# migrate with no eligible files stays a reported error, unlike the real tool's silent success

`cli/migrate.py` raises `CommandError("no-eligible-files-to-migrate", ...)`
(exit 1) when no candidate files need migration. The real adrplus returns
success (exit 0, "No files need migration.") for the identical situation.

**Why kept as-is, not changed to match:** confirmed live (Milestone 8
audit, fidelity finding F8) that neither tool changes any bytes on disk
in this case — the divergence is purely about the reported outcome, not
behavior. adrpy-ai's own convention elsewhere already treats "the
requested operation found nothing to do" as a reported failure (e.g.
`no-decisions-found` earlier in this same command, and other commands'
own empty-result codes) — matching the real tool's inconsistency here
(silent success for one kind of "nothing found", an error for another)
would trade internal consistency for fidelity with no clear benefit to
an agent caller. Escalated and confirmed with the user.
