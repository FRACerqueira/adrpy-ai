# Shared environment for seed.sh / reference.sh / run_batch.sh (source it).
# Everything resolves under this harness folder (a copy made OUTSIDE any git repository, see
# README.md); nothing here touches the adrpy repository or ~/.claude.
R44="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"          # POSIX form
R44W="$(cygpath -m "$R44")"                                    # C:/... form
if git -C "$R44" rev-parse --show-toplevel >/dev/null 2>&1; then
  echo "refusing to run inside a git repository ($R44): copy this folder outside any repository first (README.md)" >&2; exit 2
fi
# Base (non-venv) Python interpreter that runs the frozen adrpy copy.
BASEPY="$(cygpath -m "${AGENT_EVAL_PYTHON:?set AGENT_EVAL_PYTHON to a base Python 3.12 interpreter (README.md)}")"
export AGENT_EVAL_PYTHON="$BASEPY"
SCENARIOS_ALL="S0 S1 S2 S3 S4 S5 S6 S7 S8 S9 S10 S11 S12"

# Round 46: a run label is <model>:<label> (opus:S3, sonnet:S3b, haiku:S10b); its dirs are
# work/<model>-<label>, out/<model>-<label>.*, env/<model>-<label>. The same map is in evaluate.py.
declare -A MODEL_IDS=([opus]=claude-opus-5-5 [sonnet]=claude-sonnet-5 [haiku]=claude-haiku-4-5-20251001)
# parse_label LABEL -> sets PL_MODEL, PL_DIR, PL_BASE (scenario id S<n>); returns 1 when malformed.
parse_label() {
  [[ "$1" =~ ^(opus|sonnet|haiku)[:-](S([0-9]+)[b-z]?)$ ]] || return 1
  PL_MODEL="${BASH_REMATCH[1]}"; PL_DIR="${BASH_REMATCH[1]}-${BASH_REMATCH[2]}"; PL_BASE="S${BASH_REMATCH[3]}"
}

# Isolated per-name environment for adrpy install-level config and temp files.
# HOME/USERPROFILE are NOT touched here (claude needs real credentials); the
# adrpy shims force their own scratch HOME for the python process only.
r44_env() {   # $1 = name (scenario id, or "seed"/"ref-S1"/...)
  local e="$R44/env/$1"
  mkdir -p "$e/appdata" "$e/local" "$e/tmp" "$e/toolhome"
  export APPDATA="$(cygpath -w "$e/appdata")" LOCALAPPDATA="$(cygpath -w "$e/local")"
  export TMP="$(cygpath -w "$e/tmp")" TEMP="$(cygpath -w "$e/tmp")" TMPDIR="$e/tmp"
  export R44_TOOL_HOME="$e/toolhome"
  export PYTHONDONTWRITEBYTECODE=1
  case ":$PATH:" in *":$R44/bin:"*) ;; *) export PATH="$R44/bin:$PATH";; esac
}

# Run the frozen adrpy directly (no shim log) -- used for snapshots/evaluation.
r44_adrpy() { HOME="$R44/env/_eval_home" USERPROFILE="$(cygpath -w "$R44/env/_eval_home")" \
  PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$R44W/pkg" "$BASEPY" -B -s -m adrpy "$@"; }

GIT_SEED=(git -c user.name=agent-eval-seed -c user.email=agent-eval-seed -c core.autocrlf=false -c commit.gpgsign=false)
