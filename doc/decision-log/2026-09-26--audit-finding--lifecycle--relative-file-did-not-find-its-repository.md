# A --file relative to the current directory did not find its repository from a subfolder

**Front:** Round 47: first use from outside | **Severity:** Medium | **Resolution:** Direct | **Round:** 47

Run from inside doc/adr, `adrpy undo --file ADR005V01R01-x.md` (or ./, ../adr/, adr/ from doc/) failed with cannot-determine-root-path: find_repo_root walked the relative path's own parents, which stop at '.'. The path is made absolute before the walk. Red then green with a test over the four relative forms; firstuse.sh ran it on Linux, macOS and Windows (d3e900f).
