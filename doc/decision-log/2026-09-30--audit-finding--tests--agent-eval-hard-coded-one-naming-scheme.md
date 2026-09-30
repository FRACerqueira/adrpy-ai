# tools/agent-eval hard-coded one decision naming scheme and broke under the default sizes

**Front:** Label sweep for 3-digit decision labels, checked with refreeze.sh (no AI needed) | **Severity:** Low | **Resolution:** Direct | **Round:** 50

tools/agent-eval spelled decision names in one fixed scheme: seed.sh looked for ADR0001V01-*, reference.sh and evaluate.py named ADR0001V01-... files and a --001 successor suffix, and the S11 prompt said ADR001. After the default sizes changed (lenseq 4, a revision on every file), refreeze.sh stopped at seed.sh: `adrpy init` now names the first decision ADR0001V01R01-...

Fix: adrnames.py builds, parses and normalizes decision names from a repository's .adrpy.json, and every script uses it. The seeds set their naming sizes explicitly (AGENT_EVAL_LENSEQ, AGENT_EVAL_LENVERSION, AGENT_EVAL_LENREVISION, default 4/2/2), so a run no longer changes with adrpy's defaults. controls.sh compares the R45 table with the names made width-free.

The same check found three more stale assumptions, fixed with it. The S2 successor regex (--001\.md$) did not match --0001.md. S12 looked for the config's old file name, so a denied sed on .adrpy.json scored CORRECT instead of WRONG. The generated INDEX.md was listed as a decision.

Red: refreeze.sh stopped at seed.sh. Green: it ends with exit 0 and all five control tables match (130 rows), with sizes 4/2/2, 3/2/0 and 5/3/1 alike and no script edited between the runs. Not covered: header and status labels are still en-us literals in evaluate.py; the seeds use the default language.
