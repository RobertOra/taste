#!/bin/bash
set -eo pipefail
cd /Users/robert/Projects/taste
step() { echo "[$(date +%H:%M:%S)] $*"; }
step community;  uv run python -I pipeline/derive_community.py --half lb --horizon 12 2>&1 | grep -v '▕' | tail -3
step song_bets;  uv run python -I pipeline/derive_song_bets.py lb 2>&1 | grep -v '▕' | tail -3
step scene_bets; uv run python -I pipeline/derive_scene_bets.py lb 2>&1 | grep -v '▕' | tail -3
step comm_prior; uv run python -I pipeline/derive_comm_prior.py lb 2>&1 | grep -v '▕' | tail -3
step done
