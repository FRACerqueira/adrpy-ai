# Orphaned temps of a decision named with an upper-case .MD were never swept

**Front:** Round 48: R47 boundaries (Opus 5.5 and Fable 5.1) | **Severity:** Low | **Resolution:** Direct | **Round:** 48

Windows reads ADR001V01-x.MD as a decision and writes its temp next to it, but Round 47's folder sweep matched only a lower-case .md target, so both the 16-hex and 32-hex temps of such a file stayed forever (pre-Round 47 the 32-hex one was swept). Both passes found it independently. The extension is now matched in any case; the hex stays case-sensitive. Red then green (208e32a).
