# Decisions index: bracketed legacy link text, a silent legacy left-out, and an interrupt after the write

**Front:** Decisions index and decision log (round 52) | **Severity:** Low | **Resolution:** Direct | **Round:** 52

A legacy name with `[` or `]` rendered as text, not a link: its link text escapes them and `\`. Once some decision has a header, config and init named nothing when a legacy decision with no header was left out (check refuses it): it is named, except a 0-byte one migrate already names. A Ctrl+C while naming the previous folder's index answered `interrupted` with no data although the config was written: that step now warns instead, and init resolves the folders before the write.
