# parse_flags rejects repeated and swallowed flags; atomic_write survives a swept temp; log retry converges

**Front:** Round 38: usability, stability and multi-write recoverability fronts | **Severity:** Low | **Resolution:** Direct | **Round:** 38

Low findings fixed red/green in c4fdb92:
- parse_flags: a flag given twice is now a usage-error instead of last-wins. A flag of the same command in a value position (`-p --path x`) is reported as a missing value. A value that merely looks like an unknown flag is still accepted.
- atomic_write_bytes/chunks: a temp file removed before os.replace by a concurrent sweep (the writer stalled over 30s, or a skewed network-share clock) is now rewritten and retried. A missing destination folder still fails at once.
- The orphan sweep no longer reports 'could not be removed' for a temp that vanished between scan and stat.
- log: an identical retry after log-index-regeneration-failed hit log-entry-already-exists forever. The already-exists path now regenerates INDEX.md first, so the index converges.
- doc/skills/README.md: the documented no-lock limitation now names its cross-file consequence, a stub left pointing at a removed shared doc.
