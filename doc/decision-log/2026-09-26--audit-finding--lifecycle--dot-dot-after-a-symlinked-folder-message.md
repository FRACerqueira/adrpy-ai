# A --file with .. after a symlinked folder was refused with a misleading message

**Front:** Round 49: R48 changes and the symlink target (Fable 5.1) | **Severity:** Low | **Resolution:** Escalated | **Round:** 49

Since Round 48 the root walk collapses '..' without following links, so a path the OS resolves to a real decision through a symlinked folder got cannot-determine-root-path, saying there is no config above it. The owner chose to keep the refusal and say why: the detail adds that the path is read as written and gives the real path. The independent review found the first condition also fired for a '..' before a link, where the sentence is false; it now fires only when collapsing '..' changes which file is meant. Red then green on POSIX (f57d438).
