# The log index linked and named entries in subfolders by their bare name

**Front:** Decisions index and decision log (round 52) | **Severity:** Medium | **Resolution:** Direct | **Round:** 52

folderlog is scanned recursively (ADR0007V01), but each entry was recorded by path.name: an entry in a subfolder linked to a file of that name at the log's root (another entry, or nothing), and log's refusals named `notes.md` where check named `b/notes.md`. Entries, links, messages and data.file now use the path in the log folder, the way the decisions index already does.
