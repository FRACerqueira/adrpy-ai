# adrpy-skills and architecture docs corrected: crossed-block wording, sweep exception, supersede family, help shape

**Front:** Round 38: doc-drift and usability fronts | **Severity:** Low | **Resolution:** Direct | **Round:** 38

Fixed in 61e4d64:
- doc/skills/README.md: the malformed crossed-block wording was inverted; it is the block that wraps another that is malformed (written in Round 37 by the same agent). The orphaned-temp sweep is now named as the one deletion that needs no --force. unknown-command and internal-error are named as codes any command can return.
- install/remove: the --force text now also names malformed.
- list: describe() says drifted is also true for a malformed block.
- doc/architecture.md:
  - a supersede successor gets a new sequence number (a new family), not 'the same family';
  - the write-command list now includes init and installconfig;
  - the adrpy-skills request flow shows the sweep;
  - help returns {commands} (hint only on the bare listing).
- supersede-successor-write-failed now documents data.intended_successor.
