# adrpy-skills refuses to write or delete through a link leading outside the target unless --allow-external-links

**Front:** Round 38: filesystem-security front (front rated Medium; raised to High by the coordinator) | **Severity:** High | **Resolution:** Escalated | **Round:** 38

_resolve_path joined --path to a constant template with no real-path containment. With .claude/skills junctioned elsewhere:
- install wrote outside the repository;
- a plain remove, without --force, deleted a tool-written file in another directory;
- both reported the in-repo path;
- an AGENTS.md that is itself a link would get its target's content copied into the repository.
The core decisions-folder sweep's rglob also followed a junction out of the folder. The project owner chose to refuse, with an explicit opt-out flag. Implemented in 804c359: install/remove resolve every file they may write or delete, and refuse with path-outside-repository (data.file/data.resolved) before any side effect when one leaves --path (or the home directory, for --target global). --allow-external-links opts in, since dotfiles links are legitimate. The core sweep now filters with is_within. Red was confirmed with real junctions; a positive control confirms a link staying inside the target is still fine.
