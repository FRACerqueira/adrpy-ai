# guards added in Rounds 39-40 now have tests that kill the mutants which survived

**Front:** Round 40: test-adequacy front | **Severity:** Medium | **Resolution:** Direct | **Round:** 40

Round 40's test-adequacy front ran 96 mutants over the recent guards; the ones that survived now have tests (5b3b2a0): the BOM strip in the family scan (a Superseded sibling saved with a BOM), has_header_shape's 12-line window and its separator-only branch, --resume onto a placeholder whose orphan was already superseded, revise counting only its own version's revisions, several invalid files named in data.unparseable_files, the ignored-file warning reported once, remove's warning for an unmarked indented copy, an existing shared doc still updated, a BOM at a later chunk boundary kept as body, a Ctrl+C before any write propagating as is, the not-resumable reason texts, and version's refusal precedence. Weak assertions tightened (explore's no-header reason).
