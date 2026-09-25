# an interruption after a commit returns interrupted with data (applied/pending/repair; data.file for log)

**Front:** Round 43: crash resilience | **Severity:** Low | **Resolution:** Direct | **Round:** 43

A Ctrl+C between supersede's or reject's two commits (e.g. during the retry backoff) returned a bare interrupted with no data, and log's entry-then-INDEX gap likewise, although the successor was on disk. commit_in_order now raises interrupted with data.applied, data.pending and data.repair once a file is committed; log carries data.file. The validator still reports the state. Red/green. Fixed in c7331d0.
