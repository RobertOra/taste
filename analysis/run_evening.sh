#!/bin/zsh
# Evening queue (one heavy job at a time): waits for the scene-bets build, then the rest.
cd "${0:A:h}/.."
while kill -0 93589 2>/dev/null; do sleep 20; done
echo "scene bets finished $(date +%H:%M)"
step() { echo "== $1 $(date +%H:%M)"; shift; "$@" 2>&1 | grep -v '▕' | tail -12 || echo "FAILED"; }
step features uv run python -I pipeline/derive_user_features.py explore
rm -f data/derived/community/explore_h12.parquet
step community uv run python -I pipeline/derive_community.py --horizon 12
step songs uv run python -I pipeline/derive_song_bets.py explore
step lb_songs uv run python -I pipeline/fetch_lb_popularity.py recording
echo "EVENING QUEUE DONE $(date +%H:%M)"
