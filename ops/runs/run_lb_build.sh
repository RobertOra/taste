#!/bin/bash
set -eo pipefail
cd /Users/robert/Projects/taste
step() { echo "[$(date +%H:%M:%S)] $*"; }
step bets;               uv run python -I pipeline/derive_bets.py lb 2>&1 | grep -v '▕' | tail -3
step user_artist;        uv run python -I pipeline/derive_user_artist.py lb 2>&1 | grep -v '▕' | tail -2
step market;             uv run python -I pipeline/derive_market.py lb 2>&1 | grep -v '▕' | tail -3
step user_features;      uv run python -I pipeline/derive_user_features.py lb 2>&1 | grep -v '▕' | tail -2
step user_year_features; uv run python -I pipeline/derive_user_year_features.py lb 2>&1 | grep -v '▕' | tail -2
step scenes_yearly;      uv run python -I pipeline/derive_scenes_yearly.py lb 2>&1 | grep -v '▕' | tail -4
step obsession;          uv run python -I pipeline/derive_obsession.py lb --artists-only 2>&1 | grep -v '▕' | tail -2
step done
