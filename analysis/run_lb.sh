#!/bin/zsh
# The one-time ListenBrainz run (plan: LB_PREREG.md, frozen before this runs). Each step runs once; failures are logged.
cd "${0:A:h}/.."
CTRL=(--scene yearly200 --age --momentum 5 --country --release --adjust additive)
LOG=analysis/out/lb_run.log
say() { echo "== $* $(date +%H:%M)" >> $LOG; }
run() { local name=$1; shift; if "$@" > analysis/out/lb_$name.log 2>&1; then say "done $name"; else say "FAILED $name"; fi; }
say "start"
run A_main   uv run python -I analysis/taste_models.py --half lb --model A --unit artist --cand lb_A_artist_main --perms 10 "${CTRL[@]}" --bets-out data/derived/bet_outcomes/A_artist_lb.parquet
run A_eval   uv run python -I analysis/evaluate.py lb_A_artist_main
run D_main   uv run python -I analysis/taste_models.py --half lb --model D --unit artist --cand lb_D_artist_main --perms 10 "${CTRL[@]}" --bets-out data/derived/bet_outcomes/D_artist_lb.parquet
run D_eval   uv run python -I analysis/evaluate.py lb_D_artist_main
run pickers  uv run python -I analysis/pickers.py --half lb --rate-by A
run headlines uv run python -I analysis/headlines.py --half lb
run ladder   uv run python -I analysis/ladder.py --half lb
run fanvalue uv run python -I analysis/fan_value.py --half lb
run obsession uv run python -I analysis/obsession.py --half=lb A_artist
run obstaste uv run python -I analysis/obs_taste.py --half lb
run recency  uv run python -I analysis/recency.py --half lb
run badtaste uv run python -I analysis/bad_taste.py --half lb
run genre    uv run python -I analysis/genre.py --half lb --test "Indie & alternative|Jazz, blues & classical"
run genre2   uv run python -I analysis/genre2.py --half lb
run learning uv run python -I analysis/learning.py --half lb
uv run python -I analysis/lb_report.py >> $LOG 2>&1
say "LB RUN DONE"
