# The agent invented options, drivers and deciders taken from git; it now writes only what the user gave, asks about open sections and closes asking for a review

**Front:** Round 45: real agent via claude -p (revalidation batches 1-5) | **Severity:** Medium | **Resolution:** Escalated | **Round:** 45

The skill's 'the text below the header is written by hand' was read as licence: S1 invented Considered Options (MySQL, MongoDB) and S1/S2 wrote Deciders from the git identity. Owner decision (a single mode, no flag): only what the user gave, open sections asked about, nothing invented, no Deciders or dates from the environment, and a review request. The review request was missed in 2/2 and then 2/3 runs; after moving it into one closing sentence with the open-sections question, batch 5 had it in 6/6 runs, including an asked-for accept (572c5c7).
