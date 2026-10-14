#!/bin/bash
set -e
cd /Users/robert/Projects/taste
CTRL=(--scene yearly200 --age --momentum 5 --country --release --adjust additive)
echo "[$(date +%H:%M)] per-bet outcomes (sealed)"
uv run python -I analysis/taste_models.py --half sealed --model A --unit artist --cand obs_A_artist_sealed --perms 1 \
  --bets-out data/derived/bet_outcomes/A_artist_sealed.parquet "${CTRL[@]}" > data/hs_models.log 2>&1
echo "[$(date +%H:%M)] obsession (sealed, artists)"
uv run python -I pipeline/derive_obsession.py sealed --artists-only 2>&1 | grep -v '▕' | tail -2
echo "[$(date +%H:%M)] pickers (sealed)"
uv run python -I analysis/pickers.py --half sealed --rate-by A 2>&1 | grep -v '▕' | grep -E "==|swap|target|panel"
echo "[$(date +%H:%M)] headlines (sealed)"
uv run python -I analysis/headlines.py --half sealed 2>&1 | tail -20
echo "[$(date +%H:%M)] done"
