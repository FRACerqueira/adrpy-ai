# The revise example did not run on a Quick Start repository, and help texts carried internal wording

**Front:** Round 47: first use from outside | **Severity:** Medium | **Resolution:** Direct | **Round:** 47

doc/commands/revise.md showed a file the documented flow never creates and left out that revisions are off by default; revision-not-configured did not name the fix. The example now turns lenrevision on first and says later names carry R01, and the detail names `adrpy config --path <root> --lenrevision 2`. Help texts named the internal parse_flags and said 'see the description above' about a text that was not there; CONTRIBUTING's test count was stale and was dropped (d3e900f).
