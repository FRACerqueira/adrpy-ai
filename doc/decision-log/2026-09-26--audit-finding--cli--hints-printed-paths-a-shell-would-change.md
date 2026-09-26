# Next-step hints printed paths a shell would split or expand, and init without --path

**Front:** Round 48: R47 boundaries (Opus 5.5) | **Severity:** Low | **Resolution:** Escalated | **Round:** 48

config-not-found and revision-not-configured interpolated the path unquoted, and cannot-determine-root-path suggested `adrpy init`, which needs --path. The owner chose to quote only when needed; the review then showed double quotes still let bash and PowerShell expand $ and backticks, cmd expand %, and a " end the quoting, so a printed command could run something else. core/text.shell_argument now double-quotes a path with whitespace, shell punctuation or a backslash and shows a placeholder when it holds ", $, `, % or !. The hint says `adrpy init --path .`. Red then green (208e32a).
