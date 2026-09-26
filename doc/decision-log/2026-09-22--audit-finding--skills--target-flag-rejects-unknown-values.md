# --target now rejects an unrecognized value, matching --provider/--skill

**Front:** Round 37: usability front | **Severity:** Medium | **Resolution:** Direct | **Round:** 37

The usability front (rated Medium-High) found --target accepted any string and silently fell back to project scope for a typo, while --provider/--skill already raised a usage error for unknown values. _validate_scope now raises UsageError for anything but project/global (7ff3c82); install/remove describe() and doc/skills/install.md/remove.md updated to name the accepted values. Recorded as Medium: a mistyped value wrote to the project instead of the user's home, with no data loss.
