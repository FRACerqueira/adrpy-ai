# installconfig's bare-read response omitted updated_fields, unlike config's own precedent

**Front:** Usability | **Severity:** Medium | **Resolution:** Direct | **Round:** 11

`config.py`'s bare read always includes `updated_fields` (as `[]`); `installconfig.py`'s own bare read (both the missing-file and file-exists branches) never included the key at all -- a generic wrapper reading `data.updated_fields` unconditionally works against every `config` call but KeyErrors on an `installconfig` read, a silent divergence from the exact precedent ADR002V01 says this command's bare-read form should match.

**Fix:** added `"updated_fields": []` to both bare-read branches; `describe()` updated to state it's present on every call, read or write. adrpy-ai `1b53975`. Two existing tests extended with the new assertion.
