#!/usr/bin/env bash
# Round 46 -- runs ONE fresh `claude -p` per run label against a fresh copy of
# seeds/<S> (work/<model>-<label>), and snapshots each repo before/after into out/.
# A run label is <model>:<label>, model in opus|sonnet|haiku; <label> is a scenario id
# (S3, S10) or a repeat of it (S3b = scenario S3, run #2; S10c = S10 run #3): same seed
# and prompt, its own work/<model>-<label>, out/<model>-<label>.*, env/<model>-<label>.
#
# Usage:  bash run_batch.sh opus:S0 sonnet:S0 haiku:S0 opus:S1 sonnet:S8b ...
#         DRY_RUN=1 bash run_batch.sh <labels>    # everything except the claude call
# Model ids: opus=claude-opus-5-5, sonnet=claude-sonnet-5, haiku=claude-haiku-4-5-20251001
# (common.sh). Env overrides: TIMEOUT_S (900), BUDGET_USD (3) for every model, or per
# model TIMEOUT_S_<model> / BUDGET_USD_<model> / MODEL_ID_<model> (e.g. BUDGET_USD_opus=4).
# Probe gate: after <model>:S0 the probe must pass (init.model == that model's id, plus
# every isolation check); when it fails, that model's remaining labels are SKIPPED and the
# other models go on. Put all three S0 first so the gates run in the first minutes.
#
# Writes ONLY under this harness folder (work/, out/, env/). HOME/USERPROFILE stay real so
# claude finds its credentials; the claude process itself will still update
# its own state under the real ~/.claude and ~/.claude.json (outside our
# control -- the coordinator owns that). The adrpy/adrpy-skills shims force a
# scratch HOME for the python process, so --target global cannot escape.
set -uo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"

DRY_RUN="${DRY_RUN:-0}"
SCEN=("$@")
[ ${#SCEN[@]} -gt 0 ] || { echo "no run labels given (e.g. opus:S0 opus:S1)" >&2; exit 2; }
OUT="$R44/out"; WORK="$R44/work"
mkdir -p "$OUT" "$WORK"

CLAUDE_BIN="$(command -v claude || true)"
[ -n "$CLAUDE_BIN" ] || { echo "claude not on PATH" >&2; exit 2; }
[ -d "$R44/seeds/S1/.git" ] || { echo "seeds missing -- run: bash refreeze.sh" >&2; exit 2; }
# The adrpy checkout the agent must not read: rendered into the settings deny rule and the S0 probe prompt.
REPO_U="$(cygpath -u "${AGENT_EVAL_ADRPY_REPO:?set AGENT_EVAL_ADRPY_REPO to the adrpy checkout (README.md)}")"; REPO_U="${REPO_U%/}"
export AGENT_EVAL_ADRPY_REPO="$REPO_U"; README_W="$(cygpath -w "$REPO_U/README.md")"
mkdir -p "$R44/env"; SETTINGS="$R44/env/_agent-settings.json"
sed "s#__ADRPY_REPO__#/$REPO_U#g" "$R44/agent-settings.json" > "$SETTINGS"

# Manifest of the harness folder outside work/out/env, to prove afterwards nothing else was written.
( cd "$R44" && find . -path ./work -prune -o -path ./out -prune -o -path ./env -prune -o -path ./ref -prune -o -type f -print | sort ) > "$OUT/_manifest.before.txt"

snapshot() {   # $1 = dir name, $2 = before|after
  local S=$1 tag=$2 d="$WORK/$1"
  ( cd "$d" && find . -path ./.git -prune -o -type f -print | sort ) > "$OUT/$S.$tag.tree.txt"
  ( cd "$d" && r44_adrpy check --path . 2>/dev/null ) > "$OUT/$S.$tag.check.json"
  if [ "$tag" = after ]; then
    ( cd "$d" && git status --porcelain=v1 --untracked-files=all ) > "$OUT/$S.after.gitstatus.txt"
    ( cd "$d" && git add -A -N . 2>/dev/null; git diff HEAD --no-color --no-ext-diff ) > "$OUT/$S.after.diff"
  fi
}

run_one() {   # $1 = dir name (opus-S3), $2 = scenario (S3), $3 = model id, $4 = timeout, $5 = budget
  local S=$1 B=$2 MODEL=$3 TIMEOUT_S=$4 BUDGET_USD=$5 d="$WORK/$1" prompt
  prompt="$(cat "$R44/prompts/$B.txt")"; prompt="${prompt//__ADRPY_README__/"$README_W"}"
  rm -rf "$d" "$R44/env/$S"; cp -a "$R44/seeds/$B" "$d"
  rm -f "$OUT/$S".*
  echo "$MODEL" > "$OUT/$S.model"
  snapshot "$S" before
  echo "[$(date +%H:%M:%S)] $S start (scenario=$B model=$MODEL timeout=${TIMEOUT_S}s budget=\$$BUDGET_USD)"
  local rc=0 t0=$SECONDS
  if [ "$DRY_RUN" = 1 ]; then
    echo "DRY_RUN: would run claude --model $MODEL in $d (timeout ${TIMEOUT_S}s, budget \$$BUDGET_USD)" > "$OUT/$S.dryrun.txt"
  else
    (
      cd "$d" || exit 97
      r44_env "$S"
      export R44_SHIMLOG="$OUT/$S.shim.log"; : > "$R44_SHIMLOG"
      unset CLAUDECODE CLAUDE_CODE_ENTRYPOINT CLAUDE_CODE_SSE_PORT ANTHROPIC_MODEL
      timeout -k 30 "$TIMEOUT_S" "$CLAUDE_BIN" -p "$prompt" \
        --model "$MODEL" \
        --output-format stream-json --verbose \
        --settings "$(cygpath -m "$SETTINGS")" \
        --setting-sources project,local \
        --permission-mode acceptEdits \
        --permission-prompts none \
        --tools Bash,Read,Edit,Write,Glob,Grep,Skill \
        --strict-mcp-config \
        --no-session-persistence \
        --max-budget-usd "$BUDGET_USD" \
        < /dev/null > "$OUT/$S.jsonl" 2> "$OUT/$S.stderr.txt"
    ); rc=$?
    # out/<S>.json = the final `result` event of the stream (single JSON object).
    "$BASEPY" -B - "$OUT/$S.jsonl" "$OUT/$S.json" <<'EOF'
import json, sys
res = None
for line in open(sys.argv[1], encoding="utf-8", errors="replace"):
    line = line.strip()
    if not line: continue
    try: ev = json.loads(line)
    except ValueError: continue
    if ev.get("type") == "result": res = ev
json.dump(res if res is not None else {"type": "result", "missing": True}, open(sys.argv[2], "w", encoding="utf-8"), indent=2)
EOF
  fi
  echo "$rc" > "$OUT/$S.exitcode"
  echo "$((SECONDS - t0))" > "$OUT/$S.seconds"
  snapshot "$S" after
  echo "[$(date +%H:%M:%S)] $S done rc=$rc in $((SECONDS - t0))s"
}

declare -A GATE_FAILED=()
for L in "${SCEN[@]}"; do
  if ! parse_label "$L" || [ ! -f "$R44/prompts/$PL_BASE.txt" ]; then
    echo "unknown run label $L (want <opus|sonnet|haiku>:S<n>[b-z])" >&2; continue
  fi
  M="$PL_MODEL"
  if [ -n "${GATE_FAILED[$M]:-}" ]; then
    echo "[$(date +%H:%M:%S)] $PL_DIR SKIPPED: the $M S0 probe failed" | tee -a "$OUT/_skipped.txt"; continue
  fi
  idv="MODEL_ID_$M"; tv="TIMEOUT_S_$M"; bv="BUDGET_USD_$M"
  mid="${!idv:-${MODEL_IDS[$M]}}"
  run_one "$PL_DIR" "$PL_BASE" "$mid" "${!tv:-${TIMEOUT_S:-900}}" "${!bv:-${BUDGET_USD:-3}}"
  if [ "$PL_BASE" = S0 ] && [ "$DRY_RUN" != 1 ]; then
    if ! "$BASEPY" -B "$R44W/evaluate.py" --probe-gate "$PL_DIR" | tee "$OUT/$PL_DIR.probe.txt"; then
      GATE_FAILED[$M]=1
      echo "$PL_DIR probe FAILED -- the remaining $M labels are skipped; see out/$PL_DIR.* and out/$PL_DIR.probe.txt." >&2
    fi
  fi
done

( cd "$R44" && find . -path ./work -prune -o -path ./out -prune -o -path ./env -prune -o -path ./ref -prune -o -type f -print | sort ) > "$OUT/_manifest.after.txt"
"$BASEPY" -B "$R44W/evaluate.py" | tee "$OUT/_evaluation.txt"
