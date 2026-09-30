# headerdisclaimer and headermigrated accepted `-->`, which closes the comment they are written in

**Front:** Header recognition and the user's own files (round 52) | **Severity:** Low | **Resolution:** Escalated | **Round:** 52

`config --headerdisclaimer "Managed --> keep"` was accepted and every new header then showed `keep (1-12) -->` as text; headermigrated likewise inside the migrated fields row's comment. Recognition was unaffected. The owner chose to refuse it where it is set only: config and installconfig answer config-field-contains-forbidden-character for a value holding `<!--` or `-->`, while a config already holding one keeps loading (a read-time refusal would break it).
