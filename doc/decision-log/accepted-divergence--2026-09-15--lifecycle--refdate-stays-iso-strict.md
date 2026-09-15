# --refdate parsing stays strict ISO-8601, diverging from the real tool's culture-aware parsing

`core/lifecycle.parse_refdate` accepts only `YYYY-MM-DD` (`date.fromisoformat`).
The real adrplus parses `--refdate` with .NET's culture-aware
`DateTime.TryParse` under the `en-US` culture, which accepts a much wider
(and more ambiguous) set of formats — confirmed live: `'01-01-2026'` is
accepted there as **January 1st** (MM-DD-YYYY), `'2026-1-1'` and
`'2026-01-01T10:00:00'` are also accepted — while it *rejects* the
compact `'20260101'` form that adrpy-ai's ISO parser accepts.

**Why kept as a deliberate divergence, not fixed to match:** replicating
the real tool's format would reintroduce genuine day/month ambiguity
(is `01-02-2026` January 2nd or February 1st?) into a CLI whose primary
caller is an AI agent constructing date strings programmatically — the
exact kind of ambiguity the project's own JSON/args-in contract exists to
avoid elsewhere. Escalated and confirmed with the user (Milestone 8 audit,
fidelity finding F3): keep the current strict, unambiguous ISO format.
