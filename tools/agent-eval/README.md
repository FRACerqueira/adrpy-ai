# agent-eval: real-agent evaluation harness (UNMAINTAINED)

**Status: unmaintained development reference.** This is not a test suite, it
is not run by CI or by `pytest`, and it is not shipped in the sdist or the
wheel. It is kept so the way the skills were evaluated can be read and, if
needed, re-run. Expect to adapt it before running it again.

## What it is

The harness runs real-agent scenarios S0 to S12 (`prompts/S*.txt`). Each
scenario is a small git repository, seeded by `seed.sh`, that holds only what
`adrpy-skills` installs for the Claude provider. For every scenario and model,
a fresh `claude -p` session runs against a fresh copy of the seed, and the
repository is snapshotted before and after the run.

- `evaluate.py` scores each run from the repository diff, the shim log of
  every `adrpy` call and the stream-json transcript. The verdicts are CORRECT,
  CORRECT-LOWER, ASKED-GATE, WRONG, HACK, OVERREACH and a few others, and each
  verdict comes with flags.
- `S0` is an isolation probe. If it fails, the remaining runs for that model
  are skipped.
- Controls: `reference.sh` builds scripted positive and negative runs under
  `ref/`. `controls.sh` scores them against the hand-written tables in
  `expected/`, so any change to the evaluator's rules shows up as a
  difference.
- The models are `opus`, `sonnet` and `haiku`. The model IDs are in
  `common.sh` and `evaluate.py`.
- `BATCH4.txt` is an example batch plan, kept as it was written for Round 46.

## SAFETY

`swap_and_run.sh` temporarily **replaces the operator's GLOBAL
`~/.claude/CLAUDE.md`** with a placeholder, so that the agent under test sees
no personal instructions. It then restores the file:

- It refuses to swap unless the file's sha256 equals
  `AGENT_EVAL_EXPECTED_CLAUDE_MD_SHA256`.
- It backs the file up to `CLAUDE.md.backup` and checks the backup's hash.
- It restores the file on EXIT, INT and TERM, then checks the restored file's
  hash (see `out/_swap.log`).

Run it only knowingly, and keep your own backup of that file first. If a
session dies mid-batch, compare the file with `CLAUDE.md.backup` yourself.
Never dry-run through `swap_and_run.sh`: it swaps even with `DRY_RUN=1`. Use
`DRY_RUN=1 bash run_batch.sh ...` instead.

The `claude` process still writes its own state under the real `~/.claude`
and `~/.claude.json`. The `adrpy` shims force a scratch HOME only for the
Python process.

## Requirements

- Windows with Git Bash. The scripts use `cygpath`, and the shims include
  `.cmd` twins.
- The `claude` CLI on PATH, logged in.
- A base Python 3.12 interpreter, not a virtual environment.
- **A copy of this folder outside any git repository.** Seeds, work
  directories and the CLAUDE.md backup are written next to the scripts.
  Inside a repository, the agent would also pick up that repository's
  instruction files. `common.sh` refuses to run inside a git work tree.

| Variable | Required by | Meaning |
|---|---|---|
| `AGENT_EVAL_PYTHON` | all scripts | Base Python interpreter that runs the frozen adrpy copy |
| `AGENT_EVAL_ADRPY_REPO` | `refreeze.sh`, `run_batch.sh`, `swap_and_run.sh` | adrpy checkout: `src/adrpy` is frozen from it, and the agent is denied reading it |
| `AGENT_EVAL_EXPECTED_CLAUDE_MD_SHA256` | `swap_and_run.sh` | sha256 of your real global CLAUDE.md; no swap when unset or different |
| `AGENT_EVAL_CLAUDE_MD` | `swap_and_run.sh` (optional) | File to swap; default `$HOME/.claude/CLAUDE.md` |
| `AGENT_EVAL_R44_REAL_DIR` | `reference.sh` (optional) | Real Round 44 run artifacts for the `r44-real` control; not archived, and its rows are skipped without it |
| `TIMEOUT_S`, `BUDGET_USD`, `*_<model>`, `MODEL_ID_<model>` | `run_batch.sh` (optional) | Per-run limits and model ID overrides |

## How to run

```bash
cp -r tools/agent-eval <dir-outside-any-repo>/agent-eval
cd <dir-outside-any-repo>/agent-eval
export AGENT_EVAL_PYTHON=<path to a base python.exe 3.12>
export AGENT_EVAL_ADRPY_REPO=<path to your adrpy-ai checkout>
bash refreeze.sh          # shims, freeze src/adrpy, seeds, controls; must end with exit 0
export AGENT_EVAL_EXPECTED_CLAUDE_MD_SHA256="$(sha256sum ~/.claude/CLAUDE.md | cut -d' ' -f1)"
bash swap_and_run.sh opus:S0 sonnet:S0 haiku:S0 opus:S1 sonnet:S1 ...
tail -3 out/_swap.log     # must show RESTORED OK
less out/_evaluation.txt
```

A run label is `<model>:<scenario>[b-z]`, for example `sonnet:S5b` for the
second run of S5. Put the three `S0` probes first.

## Known limitations

- **Regex heuristics.** The evaluator decides "asked", "warning relayed" and
  similar judgements with regular expressions. Every batch needed a manual
  read of the final texts, and several rules were corrected after a batch
  (see `BATCH4.txt`).
- **Single turn.** Each session is one prompt with no follow-up and no
  approval surface. An agent that stops to ask is scored on the question
  alone.
- **Small samples.** There are n=1–2 runs per scenario and model, so a single
  run can change a percentage a lot.
- **S0 probe step 8** (`mkdir` + `git mv`) can fail when the agent chains a
  harmless `echo` into the command. Read the probe output before treating a
  failure as an isolation break.
- **One provider.** Only Claude Code was exercised. The other providers
  `adrpy-skills` supports were not.
- **Hard-coded names.** Model IDs and the Round 44–46 control tables are
  specific to when the harness was written.

## Results

- The Round 46 entries in `doc/decision-log/INDEX.md` record what the
  batches found and what was accepted. The real-agent ones have the source
  "Round 46: real-agent breadth"; the four `risk-accepted` entries dated
  2026-09-25 about the `cli`, `migrate` and `skills` scopes are also Round 46.
- The model recommendation is in `doc/skills/README.md`, "Which model to use".
