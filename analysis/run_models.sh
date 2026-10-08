#!/bin/zsh
# Models C and D, uncontrolled and fully controlled (explore half).
cd "${0:A:h}/.."
CTRL=(--scene yearly200 --age --momentum 5 --country --adjust additive)
run() {  # model, name, extra args...
  local model=$1 name=$2; shift 2
  [[ -f analysis/out/model_$model/$name/summary.json ]] && { echo "skip $model/$name"; return; }
  mkdir -p analysis/out/model_$model
  if uv run python -I analysis/taste_models.py --model $model --name $name --perms 10 "$@" > /dev/null 2> analysis/out/model_$model/$name.err; then
    rm -f analysis/out/model_$model/$name.err; echo "done $model/$name"
  else
    echo "FAILED $model/$name"
  fi
}
run D primary
run D controlled "${CTRL[@]}"
run C_lb primary
run C_lb controlled "${CTRL[@]}"
run D controlled_scene_only --scene yearly200 --adjust additive
echo "MODELS DONE"
