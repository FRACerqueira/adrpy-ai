# Sync/plugins extensibility is out of scope for this migration

**Reopen-when:** a second real Python consumer of this extensibility need appears

AdrPlus's plugin system (`activeplugins`/`disableplugins` config fields,
the `IAdrPlugin` interface, the bundled `AdrIndexer` reference plugin,
the `plugins` and `sync` commands) was not ported to adrpy-ai. The two
config fields themselves are carried in `core/config.py`'s schema
(required for byte-compatibility with the shared `adr-config.adrplus`
format — a repo initialized by the real tool, or vice versa, must still
parse cleanly), but no dispatch mechanism, no plugin loading, and neither
command exist in adrpy-ai.

**Why:** confirmed with the user at the start of the migration (harness
Fase 0 escalation) — no second consumer of this extensibility exists yet
on the Python side, so building the mechanism now would be speculative.

**Reopening condition:** revisit when a second real Python consumer of
this extensibility need appears. Today there is exactly zero.
