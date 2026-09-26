# Usage and setup errors did not say what to do next, and unknown-command exited 1 or 2 depending on the path

**Front:** Round 47: first use from outside | **Severity:** Low | **Resolution:** Escalated | **Round:** 47

config-not-found, cannot-determine-root-path, an unknown command and an unknown argument gave no next step, and the init warning told users to run a bare `adrpy installconfig`, which only reads. Each now names the command that gets past it (the adrpy and adrpy-skills usage errors point to the command's own help). `adrpy help <nosuch>` exited 1 while `adrpy <nosuch>` exited 2; the owner chose 2 everywhere (UsageError carries its code). A non-empty no-header file no longer gets the interrupted-create sentence. Red then green (d3e900f).
