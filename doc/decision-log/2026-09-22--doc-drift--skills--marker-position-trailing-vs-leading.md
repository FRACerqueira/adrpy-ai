# doc/skills/README.md said the drift marker is 'trailing'; it is actually 'leading'

**Front:** Round 33: doc-drift front | **Severity:** Low | **Resolution:** Direct | **Round:** 33

The 'Drift protection' section of doc/skills/README.md described every generated file/block's content-hash marker as 'trailing'. It is in fact leading: placed immediately after a leading frontmatter block when one is present, or at the very start of the content otherwise -- confirmed both in _insert_marker()'s own docstring and empirically, by installing real files and inspecting them. Fixed the one sentence describing this; the main project README does not repeat the wrong claim, so no other file needed correction.
