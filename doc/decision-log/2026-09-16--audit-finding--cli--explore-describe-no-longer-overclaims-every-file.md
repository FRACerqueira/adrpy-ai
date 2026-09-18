# explore's describe() no longer claims unconditional completeness

**Front:** Usability (round 7), Finding 2 | **Severity:** Medium | **Resolution:** Direct

Round 7 usability audit, Finding 2: `describe()` claimed "Lists every decision file in the repository, recognized or not" -- contradicted by the command's own warning strings for candidates excluded via `is_within` and, since round 6, subdirectories `find_unreadable_subdirectories` couldn't scan. The project has already ruled a scan's completeness safety-critical elsewhere (`folderadr-change-scan-incomplete` fails closed specifically because an incomplete scan can't be trusted) -- `explore` made the same completeness claim in its own `describe()` with no equivalent caveat, only a buried warning. Round 6's own new completeness gap (unreadable subdirectories) was never reflected back into this description, exactly the drift class this pass was sent to find.

**Fix**: `describe()` now states explore is best-effort and names the three ways a file can be missing from `decisions` (excluded via `is_within`, an unreadable subdirectory, or now an unreadable file -- see this round's companion Resilience fix) and that each is reported via `warnings` instead of silently dropped or failing the command.
