# reject's partial-success data gap and init's mis-scoped error-code documentation are fixed

**Front:** Usability (round 9), Findings 1 and 2 | **Severity:** High | **Resolution:** Direct

Round 9 usability audit, Finding 1 (HIGH): `reject`'s predecessor-family scan runs AFTER the primary write (marking this file Rejected) has already committed -- unlike every other `family_members` call in this codebase, all of which run before their command's own first write. The bare `family-scan-incomplete` `family_members` raises carried no `data.file`/`data.status`, unlike this command's other two second-phase codes (`superseded-predecessor-not-found`, `reject-predecessor-write-failed`), leaving the caller to infer the already-committed write from `warnings` alone.

Finding 2 (Medium): `init-existing-numbers-scan-incomplete` was documented only inside the `--seed` argument's own description, in the same breath as codes genuinely scoped to the already-existing-repository path -- but it can also fire on a genuinely fresh `init` (no `--seed`) if a decisions folder with an unreadable subdirectory already exists under the target.

**Fix**: `reject.py`'s predecessor-family `family_members` call now catches the `CommandError` and re-raises it with `data={"file": ..., "status": "Rejected"}`, matching its siblings' shape; `describe()` updated to state this explicitly. `init-existing-numbers-scan-incomplete` moved to `init`'s top-level `description`, which every path shares, with a note that it is NOT `--seed`-scoped like its former neighbors.
