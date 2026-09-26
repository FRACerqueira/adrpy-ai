# supersede-successor-write-failed and reject-predecessor-write-failed did not say which file failed

**Front:** Round 48: R47 boundaries (Opus 5.5) | **Severity:** Low | **Resolution:** Direct | **Round:** 48

One code covers preparing either file (and the first commit), so a failure preparing supersede's predecessor was reported under the successor's name. Both codes now carry data.failed_file, on the prepare and the commit branches alike (the review found the commit branches missing), documented on both command pages. Red then green (208e32a).
