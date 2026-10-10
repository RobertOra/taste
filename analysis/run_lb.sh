#!/bin/zsh
# The one-time ListenBrainz run (plan: LB_PREREG.md, frozen before this runs). Each step runs once; failures are logged.
cd "${0:A:h}/.."
CTRL=(--scene yearly200 --age --momentum 5 --country --release --adjust additive)
LOG=analysis/out/lb_run.log
say() { echo "== $* $(date +%H:%M)" >> $LOG; }
run() { local name=$1; shift; if "$@" > analysis/out/lb_$name.log 2>&1; then say "done $name"; else say "FAILED $name"; fi; }
say "start"
# Part 1: the 9 measures (durability is circular on ListenBrainz and not run)
for m in D A B; do for u in song artist scene; do
  extra=()
  [[ $u == artist && ( $m == A || $m == D ) ]] && extra=(--bets-out data/derived/bet_outcomes/${m}_artist_lb.parquet)
  run ${m}_${u}      uv run python -I analysis/taste_models.py --half lb --model $m --unit $u --cand lb_${m}_${u}_main --perms 10 "${CTRL[@]}" $extra
  run ${m}_${u}_eval uv run python -I analysis/evaluate.py lb_${m}_${u}_main
done; done
# Part 2: the plain-language findings (P1-P16)
run pickers    uv run python -I analysis/pickers.py --half lb --rate-by A
run headlines  uv run python -I analysis/headlines.py --half lb
run ladder     uv run python -I analysis/ladder.py --half lb
run fanvalue   uv run python -I analysis/fan_value.py --half lb
run toppickers uv run python -I analysis/top_pickers.py --half lb
run obsession  uv run python -I analysis/obsession.py --half=lb A_artist
run obstaste   uv run python -I analysis/obs_taste.py --half lb
run recency    uv run python -I analysis/recency.py --half lb
run badtaste   uv run python -I analysis/bad_taste.py --half lb
run learning   uv run python -I analysis/learning.py --half lb
run genre      uv run python -I analysis/genre.py --half lb --test "Indie & alternative|Jazz, blues & classical" "Indie & alternative|Rock & punk"
run genre2     uv run python -I analysis/genre2.py --half lb
run genre3     uv run python -I analysis/genre3.py --half lb
run genre4     uv run python -I analysis/genre4.py --half lb
uv run python -I analysis/lb_report.py >> $LOG 2>&1
say "LB RUN DONE"
