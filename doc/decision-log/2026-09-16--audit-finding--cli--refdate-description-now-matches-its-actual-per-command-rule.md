# --refdate's description now states each command's own actual lower-bound rule

**Front:** Usability (round 7), Finding 3 | **Severity:** Medium | **Resolution:** Direct | **Round:** 7

Round 7 usability audit, Finding 3: `--refdate`'s description was byte-identical across 6 commands (`new`, `approve`, `reject`, `supersede`, `version`, `revise`), but the actual lower-bound rule (and which error codes apply) differs by command: `new` has no lower bound at all (a brand new decision has no prior history); `approve`/`reject` bound against the TARGET's own history; `supersede` bounds against the predecessor's own history; `version`/`revise` bound against the LATEST family member's history instead, which can be a different file than the one named in `--file` when branching off an older Rejected sibling. The 3 error codes involved (`refdate-invalid-format`, `refdate-in-future`, `refdate-before-history`) were also never documented anywhere.

**Fix**: each command's `--refdate` description now states its own actual rule and the codes it can raise; `new`'s description correctly omits `refdate-before-history`, which it never enforces.
