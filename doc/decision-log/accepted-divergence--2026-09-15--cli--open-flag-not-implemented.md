# --open (launch an external editor) is permanently not implemented

The real adrplus's `-o/--open` flag (on `new`, `supersede`, `version`,
`revise`) opens the newly created/successor file in an editor via the
app-level `comandopenadr` setting (e.g. `code {0}`), for an interactive
human user sitting at a terminal. adrpy-ai never implements it.

**Why kept as a permanent divergence, not a gap to fill later:**
adrpy-ai's whole design is args-in/JSON-out for a non-interactive caller
(an AI agent or script) — there is no interactive session to hand an
opened editor window back to, and no app-level config layer (`adrpy.json`
equivalent) exists to hold a `comandopenadr`-style setting in the first
place. Declining permanently, not deferring: the target caller this
project is built for has no use for this feature by construction, not by
omission.
