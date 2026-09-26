# Write-path edge cases: no false file-already-exists, log validates first, refused config cleans up, sweeps skip links

**Front:** Round 44: resilience of the Round 43 additions | **Severity:** Low | **Resolution:** Direct | **Round:** 44

Four resilience gaps, each red then green (8735a28). A reservation that could not be removed made the retry's O_EXCL raise a false file-already-exists; it is now a non-retryable io-error. log wrote the entry before finding an unrecognized file in the folder; it now validates the folder first. A refused config left the folders it had created; it now removes only those, bottom-up, never a folder that existed or has content. cleanup_orphaned_temp_files_for removed a junction named like a temp; both sweeps now take only regular files (lstat + S_ISREG).
