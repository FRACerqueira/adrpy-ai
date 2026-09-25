# The 'Which model to use' section overstated the evidence; rewritten from the four batch reports

**Front:** Round 46: documentation audit (docs vs code, skill vs CLI, model guidance vs reports, ADRs) | **Severity:** Medium | **Resolution:** Direct | **Round:** 46

doc/skills/README.md said two batches (there were four), that Opus followed every rule in every run (it swapped a refused pattern once in batch 3), that Haiku ended at 85% (the last comparable measure was 80%), that no read-only scenario was tested (S9 was, and passed on all models), and credited the skill for stopping the silent move (the CLI refusal text did it). Rewritten from the reports, with the caveats: few runs per scenario, single turn, verdicts reviewed by hand, one provider (b5649f4).
