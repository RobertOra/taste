#!/bin/zsh
# One-at-a-time parameter sweeps for model A around the fully controlled base (explore half).
cd "${0:A:h}/.."
BASE=(--scene yearly200 --age --momentum 5 --country --adjust additive --perms 10)
run() {  # name, extra args...
  local name=$1; shift
  [[ -f analysis/out/prescience/$name/summary.json ]] && { echo "skip $name"; return; }
  if uv run python -I analysis/prescience.py --name $name "${BASE[@]}" "$@" > /dev/null 2> analysis/out/prescience/$name.err; then
    rm -f analysis/out/prescience/$name.err; echo "done $name"
  else
    echo "FAILED $name (see analysis/out/prescience/$name.err)"
  fi
}
mkdir -p analysis/out/prescience
for v in 0 13 39 52; do run sw_onboarding_$v --onboarding $v; done
for v in w2 w8 p10 all; do run sw_rule_$v --rule $v; done
for v in 13 52; do run sw_window_$v --window $v; done
run sw_date_first --date first
for v in 6 24; do run sw_horizon_$v --horizon $v; done
for v in 0.25 0.5 0.75 1; do run sw_weight_$v --weight $v; done
for v in rank rawcap hit; do run sw_metric_$v --metric $v; done
for v in 10 50; do run sw_bins_$v --bins $v; done
for v in 0.5 2; do run sw_smooth_$v --smooth $v; done
for v in 10 50; do run sw_minbets_$v --min-bets $v; done
for v in yearly50 yearly1000 allyears200 genre200; do run sw_scene_$v --scene $v; done
echo "ALL SWEEPS DONE"
