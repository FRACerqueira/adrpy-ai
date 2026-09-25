#!/usr/bin/env bash
# Round 46 -- re-score the scripted controls under ref/ (built by reference.sh) against the
# hand-written expected tables in expected/. Called by refreeze.sh (step 6); also runnable alone after
# `bash reference.sh`. Writes only env/_prep/control_table.refreeze.txt. Exit 0 iff all match.
#   R45 rows   -> expected/control_table.r45.r46b.txt (= control_table.r45.txt except the three
#                 S5 rows the R46-b rule D2 changes by design: pos/S5, pos-readonly/S5, r44-real/S5)
#   R46 rows   -> expected/control_table.r46-expected.txt (verdicts)
#   R46-b rows -> expected/control_table.r46b-expected.txt (verdicts + flag present/absent)
#   batch-3    -> expected/control_table.b3-expected.txt (N1/N2 fixes, S11/S12; verdicts + GUARD-TRIGGERED)
#   batch-4    -> expected/control_table.b4-expected.txt (N6/N7/N10 fixes, CHECK-NOT-FIRST without log)
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
export PYTHONIOENCODING=utf-8
mkdir -p "$R44/env/_prep"; NOW="$R44/env/_prep/control_table.refreeze.txt"; : > "$NOW"
score() {  # $1 = control root name, $2.. = labels; appends "<x>/<label>: <verdict> -- <why>" rows
  local x=$1; shift; local nt=--no-transcript; [ "$x" = r44-real ] && nt=
  [ -d "$R44/ref/$x" ] || { echo "$x/: missing (not built)" >> "$NOW"; return; }
  "$BASEPY" -B "$R44W/evaluate.py" --root "$R44/ref/$x" $nt "$@" | grep -E '^S[0-9]' | sed "s#^#$x/#" >> "$NOW"
}
flag() {  # $1 = root, $2 = label, $3 = flag name -> "flag <root>/<label> <FLAG>: present|absent"
  local n; n=$("$BASEPY" -B "$R44W/evaluate.py" --root "$R44/ref/$1" --no-transcript "$2" | grep -c "flag: $3:" || true)
  echo "flag $1/$2 $3: $([ "$n" -gt 0 ] && echo present || echo absent)" >> "$NOW"
}
for spec in "pos:S1 S2 S3 S4 S5 S6 S7" "pos-body:S1" "pos-lower:S3 S4" "pos-lower-rm:S3" "pos-readonly:S5" "blocked:S5" \
            "ask:S1" "neg:S1 S2 S3 S4 S5 S6 S7" "neg-edit:S1" "neg-bash:S1" "neg-rename:S3" "neg-mv:S3" "r44-real:S3 S5"; do
  score ${spec%%:*} ${spec#*:}
done
echo "probe-synth/S0: $("$BASEPY" -B "$R44W/evaluate.py" --root "$R44/ref/probe-synth" --probe-gate | head -1)" >> "$NOW"
n45=$(wc -l < "$NOW")
for spec in "pos:S8 S9 S10" "pos-lower:S8 S9 S10" "pos-claims:S10" "pos-mention:S8" "ask:S8 S10" "neg:S8 S9 S10" "neg-mv:S8" "neg-approve:S8" "neg-hand:S8 S10" \
            "neg-cleared:S9" "neg-migrate:S9" "neg-rename:S10"; do
  score ${spec%%:*} ${spec#*:}
done
for L in opus-S0 haiku-S0 sonnet-S0; do
  echo "probe-synth-models/$L: $("$BASEPY" -B "$R44W/evaluate.py" --root "$R44/ref/probe-synth-models" --probe-gate "$L" | head -1 | awk '{print $NF}' || true)" >> "$NOW"
done
n46=$(wc -l < "$NOW")
for spec in "ask:S5" "ask-nodest:S5" "ask-failcfg:S5" "ask-root:S5" "neg-ask:S5" "neg-mkdir:S5" "neg-title:S10" "pos-claims-quoted:S10" "pos-claims-hash:S10" \
            "pos-failcfg:S10" "pos-lower:S1" "pos-please:S1" "pos-later:S2" "pos-nondec:S8" "pos-shares:S8" "pos-hint:S3" "neg-commit:S3" "neg-hidden:S7"; do
  score ${spec%%:*} ${spec#*:}
done
flag pos S3 HINT-OPTION-NOT-NAMED; flag pos-hint S3 HINT-OPTION-NOT-NAMED; flag pos-hint S3 GIT-COMMIT-ATTEMPT
flag neg-commit S3 GIT-COMMIT-ATTEMPT; flag neg-hidden S7 HIDDEN-APPROVE; flag neg S7 HIDDEN-APPROVE; flag neg-hidden S7 NO-REVIEW-REMINDER
n46b=$(wc -l < "$NOW")
# batch 3: N1 (S6 imperative ask), N2 (S5 denied read), S11 (F1 guard), S12 (F4 guard)
for spec in "pos-imperative:S6" "neg-noask:S6" "blocked-read:S5" "pos:S11" "pos-noguard:S11" "ask:S11" "pos-lower:S11" "neg:S11" "neg-hand:S11" \
            "neg-folderlog:S11" "neg-silent:S11" "neg-moveonly:S11" "neg-rename:S11" "neg-class:S11" \
            "pos:S12" "pos-noguard:S12" "ask:S12" "pos-lower:S12" "neg:S12" "neg-hand:S12" "neg-headers:S12" "neg-approve:S12" "neg-rmdenied:S11" "blocked-mv:S11" "neg-seddenied:S12"; do
  score ${spec%%:*} ${spec#*:}
done
flag pos S11 GUARD-TRIGGERED; flag pos-noguard S11 GUARD-TRIGGERED; flag pos-lower S11 GUARD-TRIGGERED; flag neg S11 GUARD-TRIGGERED
flag pos S12 GUARD-TRIGGERED; flag pos-noguard S12 GUARD-TRIGGERED; flag pos-lower S12 GUARD-TRIGGERED; flag neg-hand S12 GUARD-TRIGGERED
flag neg S12 GUARD-TRIGGERED
nb3=$(wc -l < "$NOW")
# batch 4: N6 (denied Bash / script header lines), N7 (S12 asks), N10 (S11 missing fields), CHECK-NOT-FIRST without log
for spec in "denied-script:S2" "denied-hdr:S2" "pos-bodyscript:S2" "neg-script:S2" "pos-didyoumean:S12" "pos-finalq:S12" "neg-noq:S12" \
            "ask-fields:S11" "ask-scopenote:S11" "logfirst:S11" "mvfirst:S11"; do
  score ${spec%%:*} ${spec#*:}
done
flag denied-script S2 DENIED-ATTEMPT; flag denied-hdr S2 DENIED-ATTEMPT; flag pos-bodyscript S2 DENIED-ATTEMPT
flag logfirst S11 CHECK-NOT-FIRST; flag mvfirst S11 CHECK-NOT-FIRST; flag pos-didyoumean S12 GUARD-TRIGGERED
flag pos S12 PATTERN-SWAPPED-WITHOUT-ASKING; flag pos-lower S12 PATTERN-SWAPPED-WITHOUT-ASKING
flag neg S12 PATTERN-SWAPPED-WITHOUT-ASKING; flag pos-didyoumean S12 PATTERN-SWAPPED-WITHOUT-ASKING
rc=0
P="$R44/expected"
# ref/r44-real needs archived real-run artifacts (AGENT_EVAL_R44_REAL_DIR, reference.sh); without them its rows
# are left out of both sides of the R45 comparison.
r44real=cat; [ -d "$R44/ref/r44-real" ] || { r44real="grep -v ^r44-real/"; echo "== r44-real not built: its rows are left out of the R45 comparison"; }
if diff <(cut -c1-200 "$P/control_table.r45.r46b.txt" | $r44real) <(head -n "$n45" "$NOW" | cut -c1-200 | $r44real); then
  echo "== R45 controls: identical to control_table.r45.r46b.txt ($n45 rows; vs control_table.r45.txt only pos/S5, pos-readonly/S5, r44-real/S5 differ, by design)"
else
  echo "R45 CONTROLS CHANGED (see diff above; $NOW)" >&2; rc=8
fi
if diff <(cut -d' ' -f1-2 "$P/control_table.r46-expected.txt") <(sed -n "$((n45 + 1)),${n46}p" "$NOW" | cut -d' ' -f1-2); then
  echo "== R46 controls: verdicts as expected ($(wc -l < "$P/control_table.r46-expected.txt") rows)"
else
  echo "R46 CONTROLS DIFFER from control_table.r46-expected.txt (see diff above; $NOW)" >&2; rc=9
fi
if diff <(sed -E 's/^(flag [^:]+: [a-z]+).*/\1/; s/^([^f][^ ]* [A-Z-]+).*/\1/' "$P/control_table.r46b-expected.txt") \
        <(sed -n "$((n46 + 1)),${n46b}p" "$NOW" | sed -E 's/^(flag [^:]+: [a-z]+).*/\1/; s/^([^f][^ ]* [A-Z-]+).*/\1/'); then
  echo "== R46-b controls: verdicts and flags as expected ($(wc -l < "$P/control_table.r46b-expected.txt") rows)"
else
  echo "R46-b CONTROLS DIFFER from control_table.r46b-expected.txt (see diff above; $NOW)" >&2; rc=13
fi
if diff <(sed -E 's/^(flag [^:]+: [a-z]+).*/\1/; s/^([^f][^ ]* [A-Z-]+).*/\1/' "$P/control_table.b3-expected.txt") \
        <(sed -n "$((n46b + 1)),${nb3}p" "$NOW" | sed -E 's/^(flag [^:]+: [a-z]+).*/\1/; s/^([^f][^ ]* [A-Z-]+).*/\1/'); then
  echo "== batch-3 controls: verdicts and flags as expected ($(wc -l < "$P/control_table.b3-expected.txt") rows)"
else
  echo "BATCH-3 CONTROLS DIFFER from control_table.b3-expected.txt (see diff above; $NOW)" >&2; rc=14
fi
if diff <(sed -E 's/^(flag [^:]+: [a-z]+).*/\1/; s/^([^f][^ ]* [A-Z-]+).*/\1/' "$P/control_table.b4-expected.txt") \
        <(tail -n +"$((nb3 + 1))" "$NOW" | sed -E 's/^(flag [^:]+: [a-z]+).*/\1/; s/^([^f][^ ]* [A-Z-]+).*/\1/'); then
  echo "== batch-4 controls: verdicts and flags as expected ($(wc -l < "$P/control_table.b4-expected.txt") rows)"
else
  echo "BATCH-4 CONTROLS DIFFER from control_table.b4-expected.txt (see diff above; $NOW)" >&2; rc=20
fi
exit $rc
