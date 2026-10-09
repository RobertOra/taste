#!/bin/zsh
# The one-time sealed-half confirmation run (frozen plan: SPEC.md, Confirmation).
cd "${0:A:h}/.."
CTRL=(--scene yearly200 --age --momentum 5 --country --release --adjust additive)
LOG=analysis/out/sealed_run.log
echo "== check: explore rerun reproduces A_artist_main $(date +%H:%M)" >> $LOG
uv run python -I analysis/taste_models.py --model A --unit artist --cand check_A_artist_main --perms 2 "${CTRL[@]}" > /dev/null 2>&1 \
  && uv run python -I analysis/evaluate.py check_A_artist_main > /dev/null 2>&1
uv run python -I -c "
import json
a=json.load(open('analysis/out/cand/A_artist_main/scorecard.json'))['headline_adjusted_forward']
b=json.load(open('analysis/out/cand/check_A_artist_main/scorecard.json'))['headline_adjusted_forward']
print('reproduces' if abs(a-b) < 1e-9 else f'MISMATCH {a} vs {b}')" >> $LOG
grep -q "^reproduces" $LOG || { echo "STOPPED: explore check failed" >> $LOG; exit 1; }
echo "== sealed community prior $(date +%H:%M)" >> $LOG
uv run python -I pipeline/derive_comm_prior.py sealed > data/sealed_comm_prior_build.log 2>&1 || { echo "STOPPED: comm prior failed" >> $LOG; exit 1; }
for m in D A B C_lb; do for u in song artist scene; do
  n=sealed_${m}_${u}_main
  if uv run python -I analysis/taste_models.py --half sealed --model $m --unit $u --cand $n --perms 10 "${CTRL[@]}" > analysis/out/cand/$n.build.log 2>&1 \
     && uv run python -I analysis/evaluate.py $n > analysis/out/cand/$n.eval.log 2>&1; then echo "done $n $(date +%H:%M)" >> $LOG
  else echo "FAILED $n" >> $LOG; fi
done; done
uv run python -I analysis/confirm.py >> $LOG 2>&1
echo "SEALED RUN DONE $(date +%H:%M)" >> $LOG
