# A user's INDEX.md that adrpy could not read was replaced without a warning, in both folders

**Front:** Resilience of the INDEX.md write path (round 51 confirmation) | **Severity:** High | **Resolution:** Retraction | **Round:** 51

Round 50's fs.written_by_someone_else returned False when the read failed, assuming the write would then fail too. Replacing a file needs no right to read it: with read denied (icacls deny RD), new and log replaced the user's INDEX.md with warnings: [], and config called it the index of the previous folder, to be deleted. The mark was also matched as a substring anywhere in the first 4 KB, so a user's text quoting it made the file adrpy's.

Fix: a file that exists but cannot be read is the user's; the mark counts only as the start of one of the first four lines, split on the line ends adrpy writes (never a form feed or a Unicode separator).

Red then green: tests/test_adr_index.py and tests/test_log.py (a read-denied file in both folders, the config warning, the quoted mark, four line-separator characters; a BOM and the log's older header as positive controls). The real icacls reproduction now keeps the file with a warning.

Second opinion (independent reviewer) found no break with a realistic file. Accepted as Low: the mark at the start of line 1-4 inside a user's code block, the log's generic mark, and a symlink named INDEX.md being replaced by a regular file (code read only).
