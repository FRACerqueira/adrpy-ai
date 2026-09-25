#!/usr/bin/env bash
# Round 46 -- freeze the package under test from $AGENT_EVAL_ADRPY_REPO/src/adrpy, then rebuild
# seeds and controls and verify them.
#   0. bin/ shims (make_cmd_shims.py: bash and .cmd, for this folder and $AGENT_EVAL_PYTHON)
#   1. pkg/adrpy <- $AGENT_EVAL_ADRPY_REPO/src/adrpy (replaced; __pycache__ left out)
#   2. identity proof: diff -r -x __pycache__ source vs copy (exit 4 on any difference)
#   3. pkg/SOURCE_COMMIT: the CURRENT working tree is what gets frozen (uncommitted changes
#      included). Line 1 = `<HEAD>` when src/adrpy equals HEAD, else `<HEAD>+worktree`; line 2 =
#      "clean", or the last line of `git diff --stat HEAD -- src/adrpy` (tracked changes only),
#      plus ", <n> untracked file(s)" when `git status --porcelain` lists untracked ones there
#   4. bash seed.sh, bash reference.sh
#   5. seed facts: every seed's adrpy SKILL.md carries the migrate rule and the 3 SKILL.md are
#      identical across seeds; check per seed; S8 succeeds with the phase warning; S9's config
#      has an empty migrationpattern; S10 has exactly 2 unrecognized files; batch 3: every seed has
#      "never describe their old status as kept"; S11/S12 facts and both guards run for real;
#      batch 4: every seed has the "Never move, rename or delete a file adrpy did not write" rule,
#      and the log refusal / check warning carry the "user's file(s)" sentences
#   6. controls re-scored by controls.sh: R45 rows vs expected/control_table.r45.r46b.txt
#      (R45's table with the 3 S5 rows rule D2 changes by design), R46 rows vs
#      expected/control_table.r46-expected.txt, R46-b rows and flags vs expected/control_table.r46b-expected.txt
# Read-only on the source repo (git --no-optional-locks: no index refresh). Never touches ~/.claude.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
cd "$R44"
SRC="$(cygpath -u "${AGENT_EVAL_ADRPY_REPO:?set AGENT_EVAL_ADRPY_REPO to the adrpy checkout (README.md)}")"; SRC="${SRC%/}"
G=(git --no-optional-locks -C "$SRC")

# 0. shims
"$BASEPY" -B "$R44W/make_cmd_shims.py" "$BASEPY"

# 1. copy
rm -rf "$R44/pkg/adrpy"; mkdir -p "$R44/pkg"
cp -a "$SRC/src/adrpy" "$R44/pkg/adrpy"
find "$R44/pkg/adrpy" -type d -name __pycache__ -prune -exec rm -rf {} +

# 2. identity
if diff -r -x __pycache__ "$SRC/src/adrpy" "$R44/pkg/adrpy"; then
  echo "== identity: pkg/adrpy == $SRC/src/adrpy (diff -r -x __pycache__: no difference)"
else
  echo "IDENTITY FAILED: pkg/adrpy differs from the source working tree" >&2; exit 4
fi
# 3. provenance, computed after the identity proof so it describes the tree that was proven identical
head="$("${G[@]}" rev-parse HEAD)"
dirty="$("${G[@]}" status --porcelain -- src/adrpy)"
if [ -z "$dirty" ]; then
  line1="$head"; state=clean
else
  line1="$head+worktree"
  state="$("${G[@]}" diff --stat HEAD -- src/adrpy | tail -1 | sed 's/^ *//')"
  untracked="$(printf '%s\n' "$dirty" | grep -c '^??' || true)"
  [ "$untracked" = 0 ] || state="${state:-no tracked change}, $untracked untracked file(s)"
fi
printf '%s\n%s\n' "$line1" "$state" > "$R44/pkg/SOURCE_COMMIT"
echo "== pkg/SOURCE_COMMIT"; cat "$R44/pkg/SOURCE_COMMIT"
HOME="$R44/env/_eval_home" USERPROFILE="$(cygpath -w "$R44/env/_eval_home")" APPDATA="$(cygpath -w "$R44/env/_eval_home/appdata")"   LOCALAPPDATA="$(cygpath -w "$R44/env/_eval_home/local")" PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$R44W/pkg" "$BASEPY" -B -s -c "import adrpy, sys; p = adrpy.__file__.replace('\\\\', '/'); print('== adrpy imports from', p); sys.exit(0 if p.lower().startswith(sys.argv[1].lower() + '/pkg/') else 5)" "$R44W"

# 4. rebuild
echo "== seed.sh";      bash "$R44/seed.sh"
echo "== reference.sh"; bash "$R44/reference.sh"

# 5. seed facts
RULE='`migrate` is a one-time step, when a repository adopts adrpy.'
for S in $SCENARIOS_ALL; do
  f="$R44/seeds/$S/.claude/skills/adrpy/SKILL.md"
  grep -qF "$RULE" "$f" || { echo "RULE MISSING in $f" >&2; exit 6; }
done
echo "== all $(echo $SCENARIOS_ALL | wc -w) seeds: adrpy SKILL.md contains \"$RULE\""
RULE2='never describe their old status as kept'   # batch 3 (F5 wording)
for S in $SCENARIOS_ALL; do
  grep -qF "$RULE2" "$R44/seeds/$S/.claude/skills/adrpy/SKILL.md" || { echo "RULE2 MISSING in seeds/$S" >&2; exit 6; }
done
echo "== all $(echo $SCENARIOS_ALL | wc -w) seeds: adrpy SKILL.md contains \"$RULE2\""
RULE3='**Never move, rename or delete a file adrpy did not write to get past a refusal**'   # batch 4 (wraps in body.md)
RULE4='If a pattern the user gave is refused, say why and ask before using another one.'   # batch 4 (wraps too)
for S in $SCENARIOS_ALL; do
  flat="$(tr '\r\n' '  ' < "$R44/seeds/$S/.claude/skills/adrpy/SKILL.md" | tr -s ' ')"   # CRLF file; no grep -q in the pipe (pipefail + SIGPIPE)
  [[ "$flat" == *"$RULE3"* ]] || { echo "RULE3 MISSING in seeds/$S" >&2; exit 6; }
  [[ "$flat" == *"$RULE4"* ]] || { echo "RULE4 MISSING in seeds/$S" >&2; exit 6; }
done
echo "== all $(echo $SCENARIOS_ALL | wc -w) seeds: adrpy SKILL.md contains \"$RULE3\" (whitespace-normalized)"
echo "== all $(echo $SCENARIOS_ALL | wc -w) seeds: adrpy SKILL.md contains \"$RULE4\" (whitespace-normalized)"
for k in adrpy decision-log pre-release-audit; do
  n="$(for S in $SCENARIOS_ALL; do sha256sum "$R44/seeds/$S/.claude/skills/$k/SKILL.md" | cut -d' ' -f1; done | sort -u | wc -l)"
  [ "$n" = 1 ] || { echo "$k SKILL.md differs across seeds ($n variants)" >&2; exit 7; }
  echo "   $k SKILL.md identical across seeds: $(sha256sum "$R44/seeds/S1/.claude/skills/$k/SKILL.md" | cut -c1-16)"
done
for S in $SCENARIOS_ALL; do
  printf '   check %s: ' "$S"; ( cd "$R44/seeds/$S" && { r44_adrpy check --path . 2>/dev/null || true; } ) | "$BASEPY" -B -c \
    "import json,sys; d=json.load(sys.stdin); print('success' if d.get('success') else d.get('code'), [e.get('code') for e in (d.get('data') or {}).get('errors') or []], len((d.get('data') or {}).get('warnings') or []), 'warning(s)')"
done
( cd "$R44/seeds/S8" && r44_adrpy check --path . ) | "$BASEPY" -B -c "import json,sys; d=json.load(sys.stdin); w=' '.join(d['data']['warnings']); sys.exit(0 if d['success'] and d['data']['decisions']==1 and '0002-team-offsite-notes.md' in w and 'not decisions' in w else 10)" \
  || { echo "S8 seed: expected check success, 1 decision and the phase warning on 0002-team-offsite-notes.md" >&2; exit 10; }
"$BASEPY" -B -c "import json,sys; sys.exit(0 if json.load(open(sys.argv[1], encoding='utf-8')).get('migrationpattern') in ('', None) else 11)" "$R44/seeds/S9/adr-config.adrplus" \
  || { echo "S9 seed: migrationpattern is not empty" >&2; exit 11; }
( cd "$R44/seeds/S10" && r44_adrpy check --path . ) | "$BASEPY" -B -c "import json,sys; d=json.load(sys.stdin); w=' '.join(d['data']['warnings']); sys.exit(0 if d['success'] and '2 .md file(s)' in w else 12)" \
  || { echo "S10 seed: expected check success with 2 unrecognized .md files" >&2; exit 12; }
echo "== seed facts: S8 phase warning, S9 empty pattern, S10 2 unrecognized files -- as expected"
# batch 3: S11 check warns about the note; S12 check sees the 2 legacy files. Then both guards are
# run for real on throwaway copies (env/_prep/guards), and the seeds must still be clean.
( cd "$R44/seeds/S11" && r44_adrpy check --path . ) | "$BASEPY" -B -c "import json,sys; d=json.load(sys.stdin); w=' '.join(d['data']['warnings']); sys.exit(0 if d['success'] and d['data']['decisions']==1 and 'team-sync-notes.md' in w and 'are not decision-log entries' in w else 15)"   || { echo "S11 seed: expected check success, 1 decision and the folderlog warning on team-sync-notes.md" >&2; exit 15; }
( cd "$R44/seeds/S12" && r44_adrpy check --path . ) | "$BASEPY" -B -c "import json,sys; d=json.load(sys.stdin); w=' '.join(d['data']['warnings']); sys.exit(0 if d['success'] and d['data']['decisions']==0 and '2 .md file(s)' in w else 16)"   || { echo "S12 seed: expected check success with 2 unrecognized .md files" >&2; exit 16; }
G3="$R44/env/_prep/guards"; rm -rf "$G3"; mkdir -p "$G3"; cp -a "$R44/seeds/S11" "$R44/seeds/S12" "$G3/"
( cd "$G3/S11" && r44_adrpy log --path . --classification scope-note --scope adr001 --slug primary-database-only --summary "x" --body "x" 2>/dev/null || true ) > "$G3/log11.json"
grep -q '"code": "log-directory-contains-unrecognized-file"' "$G3/log11.json" || { echo "S11 guard: log did not refuse" >&2; exit 17; }
# batch 4: the refusal and the check warning say the note is the user's (the new package wording)
grep -qF "it is the user's file -- ask where it belongs before moving it, and never delete it." "$G3/log11.json" || { echo "S11 guard: log refusal lacks the user's-file sentence" >&2; exit 17; }
( cd "$R44/seeds/S11" && r44_adrpy check --path . ) > "$G3/check11.json"
grep -qF "so they are the user's files: ask where they belong before moving any, and never delete one" "$G3/check11.json" \
  || { echo "S11 seed: check warning lacks the user's-files sentence" >&2; exit 15; }
for sub in config explore; do
  ( cd "$G3/S12" && r44_adrpy $sub --path . --migrationpattern N00:04T02 2>/dev/null || true )     | grep -q '"code": "config-migrationpattern-invalid"' || { echo "S12 guard: $sub N00:04T02 not refused" >&2; exit 18; }
done
for S in S11 S12; do
  [ -z "$(git -C "$G3/$S" status --porcelain)" ] || { echo "$S guard copy changed after a refusal" >&2; exit 19; }
  [ -z "$(git -C "$R44/seeds/$S" status --porcelain)" ] || { echo "seeds/$S is not clean" >&2; exit 19; }
done
rm -rf "$G3"
echo "== seed facts: S11 folderlog warning + log refused; S12 2 unrecognized files + config/explore N00:04T02 refused; nothing written"

# 6. controls re-scored against the expected tables (controls.sh exits non-zero on any mismatch)
bash "$R44/controls.sh"
echo "== refreeze done: $(head -1 "$R44/pkg/SOURCE_COMMIT") ($(sed -n 2p "$R44/pkg/SOURCE_COMMIT"))"
