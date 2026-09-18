# installconfig's accepted-risk docstring understated a lost update's real blast radius

**Front:** Stability | **Severity:** Low | **Resolution:** Direct | **Round:** 11

`installconfig.py`'s own accepted-risk docstring (ADR002V01: no lock, lost update is accepted) was accurate about no corruption, but understated scope: a `--seed` (wholesale replace) racing a field-edit (which reads the *existing* file as its own base, never the seed's content) can have the field-edit's write revert the entire seed replacement, not just one field, if the field-edit's write lands after the seed's.

**Fix:** one clarifying paragraph added to the docstring; no code change, the underlying risk-acceptance in ADR002V01 isn't revisited, only its documented scope. adrpy-ai `1b53975`.
