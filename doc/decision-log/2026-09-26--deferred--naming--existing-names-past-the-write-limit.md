# An existing decision whose name is 235 to 255 bytes still fails every write with a raw io-error

**Reopen-when:** a user or a test meets an existing decision name longer than 234 bytes

filename-too-long stops the tool from creating such a name, but a file renamed by hand or brought in by migrate can already have one: check accepts it, and approve, reject, undo, supersede or migrate then fail with io-error (Errno 22) when the temp file's name passes 255. The range shrank from 219 to 235 bytes with the 16-hex suffix. Deferred by the owner (Round 47 independent diff review), not fixed now: a check warning would be the likely fix.
