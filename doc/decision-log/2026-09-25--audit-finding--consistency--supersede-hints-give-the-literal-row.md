# successor-without-predecessor and superseded-not-live hints give the literal row, in order of preference

**Front:** Round 44: real agent via claude -p (S3) | **Severity:** Medium | **Resolution:** Direct | **Round:** 44

The static hints for successor-without-predecessor and superseded-not-live described the repair in prose, and S3's agent chose to rename instead. They are now built per error with status_row and the repository's own labels, numbered by preference; the successor hint adds that the --NNN suffix is the link and must not be renamed. Applying option 1 literally makes check pass for both codes (8735a28).
