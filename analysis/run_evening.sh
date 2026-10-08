#!/bin/zsh
# Evening builds, one heavy job at a time; full logs in data/<step>_build.log. Stops at the first failure.
cd "${0:A:h}/.."
for step in "songs pipeline/derive_song_bets.py explore" \
  "lb_songs pipeline/fetch_lb_popularity.py recording" "scenes pipeline/derive_scene_bets.py explore"; do
  name=${step%% *}; cmd=${step#* }
  echo "== $name $(date +%H:%M)"
  if ! uv run python -I ${=cmd} > data/${name}_build.log 2>&1; then
    echo "-- $name FAILED $(date +%H:%M)"; grep -vE '▕|^\s+\^|^\s+~' data/${name}_build.log | tail -6; exit 1
  fi
  echo "-- $name ok $(date +%H:%M)"; grep -vE '▕|^\s+[0-9]+\.[0-9]s' data/${name}_build.log | tail -3
done
echo "EVENING QUEUE DONE $(date +%H:%M)"
