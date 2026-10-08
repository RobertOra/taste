#!/bin/zsh
# Evening queue (one heavy job at a time).
cd "${0:A:h}/.."
step() { echo "== $1 $(date +%H:%M)"; shift; "$@" 2>&1 | grep -v '▕' | tail -12; echo "-- exit ${pipestatus[1]} $(date +%H:%M)"; }
rm -f data/derived/community/explore_h12.parquet
step community uv run python -I pipeline/derive_community.py --horizon 12
step songs uv run python -I pipeline/derive_song_bets.py explore
step lb_songs uv run python -I pipeline/fetch_lb_popularity.py recording
step scenes uv run python -I pipeline/derive_scene_bets.py explore
echo "EVENING QUEUE DONE $(date +%H:%M)"
