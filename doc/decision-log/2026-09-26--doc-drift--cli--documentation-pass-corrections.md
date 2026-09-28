# Documentation that no longer matched the code after Round 47

**Front:** Round 48: documentation vs code | **Severity:** Low | **Resolution:** Escalated | **Round:** 48

doc/skills/README.md still gave the 32-hex temp shape, called glue.md a verbatim copy and left interrupted and io-error out of the codes any command returns; architecture.md undercounted core modules, said only log uses the decision-log module, gave a partial sweep list and called interrupted Ctrl+C only (it also follows an unexpected error once something was written); the installconfig example read as an argument order, init --language omitted its condition, and 'a file that is not an entry' is 'a .md'. All corrected. The owner chose to document the limits filename-too-long does not cover (Windows' 260-character path with long paths off, HFS+) and to remove the comment-audit example from remove.md (208e32a).
