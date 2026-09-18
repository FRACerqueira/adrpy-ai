# explore is now best-effort about a single unreadable file, not just unreadable subdirectories

**Front:** Resilience (round 7), Finding 1 | **Severity:** High | **Resolution:** Direct | **Round:** 7

Round 7 resilience audit, Finding 1: `_build_entry`'s own `raw_bytes = path.read_bytes()` had no tolerance at all, transient or persistent -- unlike every other decision-file read in this codebase (`read_header_lines`, `read_lines_with_report`), which retries a transient `PermissionError` via the shared `io_retry` helper. One genuinely unreadable file (locked by an editor, backup tool, or antivirus -- ordinary in a folder of Markdown files people also open by hand) killed the ENTIRE inventory with a bare `io-error`, discarding every other, perfectly readable file too. Same failure class round 6 already fixed for unreadable subdirectories; explore was not yet equally best-effort about a single unreadable file.

**Fix**: `_build_entry`'s read now retries a transient `PermissionError` via the shared `read_with_permission_retry` helper; a persistent failure is caught by the scan loop and the file is skipped into a new `warnings` entry instead of aborting the whole command, matching the unreadable-subdirectory handling already in place.
