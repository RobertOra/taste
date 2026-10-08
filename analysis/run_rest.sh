#!/bin/zsh
# Oversized sweep variants (per-archive script), then model B.
cd "${0:A:h}/.."
CTRL=(--scene yearly200 --age --momentum 5 --country --adjust additive)
run() {  # model, name, extra args...
  local model=$1 name=$2; shift 2
  [[ -f analysis/out/model_$model/$name/summary.json ]] && { echo "skip $model/$name"; return; }
  mkdir -p analysis/out/model_$model
  if uv run python -I analysis/taste_models.py --model $model --name $name --perms 5 "$@" > /dev/null 2> analysis/out/model_$model/$name.err; then
    rm -f analysis/out/model_$model/$name.err; echo "done $model/$name"; else echo "FAILED $model/$name"; fi
}
run A sw_onboarding_0 "${CTRL[@]}" --onboarding 0 --user-sample 2
run A sw_rule_w2 "${CTRL[@]}" --rule w2 --user-sample 2
run A sw_rule_all "${CTRL[@]}" --rule all --user-sample 2
[[ -f data/derived/community/explore_h12.parquet ]] || uv run python -I pipeline/derive_community.py --horizon 12 2>&1 | grep -v '▕'
run B primary
run A primary_sample2 --user-sample 2 "${CTRL[@]}"
run B controlled "${CTRL[@]}"
echo "REST DONE"
