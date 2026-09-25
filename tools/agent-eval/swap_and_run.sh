#!/usr/bin/env bash
# Coordinator wrapper: swap the operator's GLOBAL CLAUDE.md for a placeholder
# only while the batch runs; always restore it (trap on EXIT/INT/TERM) and
# verify the hash. Run it only knowingly, with your own backup (README.md).
#   AGENT_EVAL_EXPECTED_CLAUDE_MD_SHA256  required: sha256 of the real file; no swap when unset or different
#   AGENT_EVAL_CLAUDE_MD                  optional: the file to swap (default: $HOME/.claude/CLAUDE.md)
set -u
R44="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL="${AGENT_EVAL_CLAUDE_MD:-$HOME/.claude/CLAUDE.md}"
BACKUP="$R44/CLAUDE.md.backup"
# Fail on a missing interpreter, repository or a harness inside a git repository BEFORE any swap.
source "$R44/common.sh"
: "${AGENT_EVAL_ADRPY_REPO:?set AGENT_EVAL_ADRPY_REPO to the adrpy checkout (README.md)}"
LOG="$R44/out/_swap.log"
mkdir -p "$R44/out"

# Never back up anything but the known real file: a rerun after a failed
# restore would otherwise overwrite the only good copy with the placeholder.
EXPECTED="$(printf '%s' "${AGENT_EVAL_EXPECTED_CLAUDE_MD_SHA256:-}" | tr 'A-F' 'a-f')"
[ -n "$EXPECTED" ] || { echo "AGENT_EVAL_EXPECTED_CLAUDE_MD_SHA256 is not set; refusing to swap" | tee -a "$LOG"; exit 3; }
orig_hash="$(sha256sum "$REAL" 2>/dev/null | cut -d' ' -f1)"
[ "$orig_hash" = "$EXPECTED" ] || { echo "CLAUDE.md is not the known original ($orig_hash); refusing to swap" | tee -a "$LOG"; exit 3; }
cp -p "$REAL" "$BACKUP"
back_hash="$(sha256sum "$BACKUP" | cut -d' ' -f1)"
echo "orig=$orig_hash backup=$back_hash" > "$LOG"
[ "$orig_hash" = "$back_hash" ] || { echo "backup hash mismatch; aborting before any swap" | tee -a "$LOG"; exit 2; }

restore() {
  cp -p "$BACKUP" "$REAL"
  now="$(sha256sum "$REAL" | cut -d' ' -f1)"
  if [ "$now" = "$orig_hash" ]; then
    echo "RESTORED OK $now" | tee -a "$LOG"
  else
    echo "RESTORE HASH MISMATCH: now=$now expected=$orig_hash -- backup at $BACKUP" | tee -a "$LOG"
  fi
}
trap restore EXIT INT TERM

printf '# Placeholder\n\nTemporarily replaced for an isolated skill test (adrpy agent-eval). The real file is restored automatically.\n' > "$REAL"
echo "SWAPPED $(date +%H:%M:%S)" >> "$LOG"

cd "$R44" && bash run_batch.sh "$@"
echo "BATCH rc=$? $(date +%H:%M:%S)" >> "$LOG"
