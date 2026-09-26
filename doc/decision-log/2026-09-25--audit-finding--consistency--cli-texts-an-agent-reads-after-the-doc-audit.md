# CLI texts an agent reads: the 0-byte legacy hint said remove it, still-proposed read as approve it, and the adoption boundary was misnamed

**Front:** Round 46: documentation audit (docs vs code, skill vs CLI, model guidance vs reports, ADRs) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 46

A 0-byte file with a legacy-scheme name got the interrupted-create hint 'remove it', though the tool only creates current-scheme names, so it is the user's file; it now says to ask before removing it, and migrate's skip warning is split by scheme. The still-proposed message read 'it must be approved first' and called a migrated placeholder Proposed; it now states what each command accepts and that accepting is the user's decision. Hints and warnings said 'decisions the tool created' where the boundary is 'a valid header migrate did not write'. Red then green; the owner approved each (b5649f4).
