#!/bin/zsh
# Build and score every candidate in EVALUATION.md (explore half). One heavy job at a time.
# Each candidate writes analysis/out/cand/<name>/{agg.parquet,meta.json}; the evaluator adds scorecard.json.
# Re-running skips candidates that already have a scorecard.
# Usage: run_candidates.sh [main|sweeps|justx|all]   (default all)
STAGE=${1:-all}
cd "${0:A:h}/.."
CTRL=(--scene yearly200 --age --momentum 5 --country --release --adjust additive)
LOG=analysis/out/cand/run.log
mkdir -p analysis/out/cand

cand() {  # name, model, unit, extra args...
  local name=$1 model=$2 unit=$3; shift 3
  [[ -f analysis/out/cand/$name/scorecard.json ]] && { echo "skip $name" >> $LOG; return; }
  local t0=$(date +%s)
  if uv run python -I analysis/taste_models.py --model $model --unit $unit --cand $name --perms 10 "$@" \
       > analysis/out/cand/$name.build.log 2>&1 \
     && uv run python -I analysis/evaluate.py $name > analysis/out/cand/$name.eval.log 2>&1; then
    rm -f analysis/out/cand/$name.build.log
    echo "done $name ($(( $(date +%s) - t0 ))s)" >> $LOG
  else
    echo "FAILED $name (see analysis/out/cand/$name.*.log)" >> $LOG
  fi
}

# Main candidates (all controls) -------------------------------------------------------------------------
if [[ $STAGE == main || $STAGE == all ]]; then
MAIN=( "A artist" "A song" "A scene" "B artist" "B song" "B scene"
       "C_lb artist" "C_lb song" "C_lb scene" "D artist" "D song" "D scene" )
for mu in $MAIN; do
  m=${mu% *}; u=${mu#* }

  cand ${m}_${u}_main $m $u "${CTRL[@]}"
done

fi
# Settings sweeps (one at a time around the main settings) ----------------------------------------------
if [[ $STAGE == sweeps || $STAGE == all ]]; then
for mu in $MAIN; do
  m=${mu% *}; u=${mu#* }
  for h in 6 24; do cand ${m}_${u}_h$h $m $u "${CTRL[@]}" --horizon $h; done
  for w in 0.5 1; do cand ${m}_${u}_w$w $m $u "${CTRL[@]}" --weight $w; done
  cand ${m}_${u}_rank $m $u "${CTRL[@]}" --metric rank
  for b in 10 50; do cand ${m}_${u}_bins$b $m $u "${CTRL[@]}" --bins $b; done
  if [[ $u == artist ]]; then
    for o in 13 52; do cand ${m}_${u}_on$o $m $u "${CTRL[@]}" --onboarding $o; done
    for r in w8 p10; do cand ${m}_${u}_rule_$r $m $u "${CTRL[@]}" --rule $r; done
    cand ${m}_${u}_rule_w2 $m $u "${CTRL[@]}" --rule w2 --user-sample 2
  fi
done

fi
# "Is it just X?" variants: remove one control at a time, plus the dating and radio checks ------------------
if [[ $STAGE == justx || $STAGE == all ]]; then
for mu in $MAIN; do
  m=${mu% *}; u=${mu#* }
  cand ${m}_${u}_nocontrols $m $u --adjust additive
  if [[ $u != scene ]]; then  # scene bets: scene/age/country/release controls don't apply
    cand ${m}_${u}_no_scene $m $u --age --momentum 5 --country --release --adjust additive
    cand ${m}_${u}_no_age $m $u --scene yearly200 --momentum 5 --country --release --adjust additive
    cand ${m}_${u}_no_country $m $u --scene yearly200 --age --momentum 5 --release --adjust additive
    cand ${m}_${u}_no_release $m $u --scene yearly200 --age --momentum 5 --country --adjust additive
  fi
  if [[ $u != song ]]; then  # songs have no momentum measure
    cand ${m}_${u}_no_momentum $m $u --scene yearly200 --age --country --release --adjust additive
  fi
  if [[ $u == artist ]]; then
    cand ${m}_${u}_first_listen $m $u "${CTRL[@]}" --date first
    cand ${m}_${u}_scene1000 $m $u --scene yearly1000 --age --momentum 5 --country --release --adjust additive
  fi
done
fi
echo "STAGE $STAGE DONE $(date +%H:%M)" >> $LOG
