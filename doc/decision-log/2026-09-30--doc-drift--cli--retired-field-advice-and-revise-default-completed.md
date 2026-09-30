# The retired-field advice left init --seed and seeds out, and revise's default read as 2 or 0

**Front:** Documentation versus code, running the examples (round 52) | **Severity:** Low | **Resolution:** Direct | **Round:** 52

The second opinion on the fix: init --seed also rewrites the repository's config without retired fields, and a seed is only read, so it keeps them; the notice now says adrpy drops them from a config it rewrites (config, installconfig, init --seed) and a file it only reads keeps them. revise's contract implied lenrevision is 2 or 0 in a new repository, where a seed may set 0 to 3: it now says the seed's value, 2 by default.
