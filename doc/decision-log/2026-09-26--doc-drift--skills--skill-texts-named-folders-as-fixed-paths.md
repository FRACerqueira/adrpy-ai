# The decision-log skill and workflow doc named doc/adr and doc/decision-log as fixed paths

**Front:** Round 47: first use from outside | **Severity:** Low | **Resolution:** Escalated | **Round:** 47

glue.md, doc/decision-log-workflow.md and doc/skills/README.md called doc/adr and doc/decision-log adrpy's fixed paths, but folderadr and folderlog are configurable. The owner chose that the texts obey the repository's config at run time: they name the folders by their fields, give the paths as defaults, and say to read the repository's values with `adrpy config --path .` (d3e900f).
