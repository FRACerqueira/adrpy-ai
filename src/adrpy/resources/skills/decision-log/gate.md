# Writing anything this skill produces requires a separate approval

The mechanics below (the ADR-vs-log triage, classification, entry format)
describe *how* to record something once you already know you're allowed to
write it. This section is the gate on *actually writing* -- to an ADR file,
or to a new entry in this decision log -- a stricter, separate approval
from anything else already agreed. It applies identically to both: an ADR
and a decision-log entry are different destinations for the same
underlying act (recording a decision), and this gate governs that act, not
the destination.

**Approving the underlying decision is never the same as approving the
write.** If a design trade-off was just resolved -- through back-and-forth
discussion, or through a structured multiple-choice question the user just
answered -- that settles *what* to do. It does not, by itself, authorize
*whether and how to record it*, whether the record in question is an ADR
or a log entry. Ask separately, every time, even when the decision was
just settled in the same turn and asking again feels like unnecessary
friction. Do not write the ADR file, do not create a new ADR
version/revision, and do not create a new decision-log entry, until that
separate question has been asked and answered.

**This gate covers every write, not only the first one, and not only
ADRs.** An ADR that already has an open running section built for exactly
this kind of entry (an audit's ongoing findings log, a decisions-so-far
appendix) carries no standing authorization to append to it. A
decision-log entry already being the "lightweight, just ask fast" record
carries no standing authorization either -- this skill's own body says
"ask before writing, every time," and that is the same gate as this one,
not a lighter version of it. Each new entry, of either kind, still needs
its own ask before the edit, even when the fix or finding it records was
already approved earlier in the same turn, and even though adding to an
already-open section or logging "just one more finding" feels like
continuing already-authorized work rather than a fresh write. That feeling
is exactly the failure mode to distrust here.

**A decision to *not* do something gets the same treatment as a decision
to do something.** Declining a feature, or deferring a deeper fix, is just
as much a decision as building something -- and it's the easier one to
undo by accident later, precisely because nothing visible marks that it
was ever decided. Treat it with the same ask-before-recording discipline.

**When in doubt about whether something is architectural enough to need
this gate at all**, use the triage test in the main body of this skill
(does this change a choice among design alternatives, with a lasting
consequence for the architecture?) -- and if that test says yes but there
is no existing decision-record tooling in this project to check against,
ask how the project owner wants it recorded, rather than assuming any
particular convention.
