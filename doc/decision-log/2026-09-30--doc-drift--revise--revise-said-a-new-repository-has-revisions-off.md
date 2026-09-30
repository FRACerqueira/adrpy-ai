# revise's contract said a new repository has revisions off, where lenrevision is 2

**Front:** Documentation versus code, running the examples (round 52) | **Severity:** Medium | **Resolution:** Direct | **Round:** 52

revise's describe() (doc/commands/revise.md, `adrpy help revise`) said lenrevision is not above 0 in a freshly initialized repository; init writes 2 and revise works there, run and confirmed, and the same page said revisions are on by default. It now says 2 in a new repository unless the seed sets 0.
