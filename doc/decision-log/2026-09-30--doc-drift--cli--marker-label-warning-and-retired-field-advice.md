# lifecycle.md over-stated who warns about a marker its label contradicts, and the retired-field advice outlived the write

**Front:** Documentation versus code, running the examples (round 52) | **Severity:** Low | **Resolution:** Direct | **Round:** 52

lifecycle.md said a label contradicting the hidden marker is reported as a warning; only a command acting on that decision warns, and explore reports it in header.marker_label_mismatches, check does not. The retired-field warning told the reader to remove fields config had just dropped: it now says config and installconfig drop them when they rewrite the file, and otherwise they are removed by hand.
