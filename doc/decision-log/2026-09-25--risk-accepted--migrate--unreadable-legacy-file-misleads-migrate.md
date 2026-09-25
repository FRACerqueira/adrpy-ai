# With an unreadable legacy file or folder, migrate refuses but its message points at the wrong cause

has_valid_header counts an unreadable file as having a header, so under an overlapping pattern migrate may add the 'already migrated' warning before refusing with migration-scan-failed; an unreadable subfolder can make it refuse the pattern before migration-scan-incomplete. Nothing is written in either case, and the scan error follows. Low, left as is (0be5f3b).
