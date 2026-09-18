# _field_description's unreachable generic fallback now fails loudly instead of silently

**Front:** Test-Adequacy (round 4, revisited round 5) | **Severity:** Medium

Round 4 test-adequacy audit, Finding 10, revisited: `_field_description`'s final fallback (`return f"New value for '{field}'."`) was confirmed genuinely unreachable given today's 26 editable fields -- every one hits a specific branch above it. Initially left as-is under the surgical-changes rule (pre-existing dead code, don't remove unless asked). Revisited because a silent generic fallback here isn't just unreachable code -- it's a latent regression waiting to happen: the exact usability defect M2 already fixed (a tautological description an agent can't learn a field's real domain from) would silently come back the moment a new field is ever added to `_EDITABLE_FIELDS` without a matching branch, and nothing would catch it.

**Fix**: raises `AssertionError` instead of returning the generic string, so that moment fails immediately (any test or `describe()` call exercising the new field) rather than shipping silently. Red/green: a test calling `_field_description` with an unrecognized field name confirmed it returned the generic string before the fix, raises after.
