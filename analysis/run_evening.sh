#!/bin/zsh
# Evening builds, one heavy job at a time; full logs in data/<step>_build.log. Skips steps whose output exists;
# stops at the first failure.
cd "${0:A:h}/.."
X=data/derived
for step in "songs:$X/song_bets/explore.parquet:pipeline/derive_song_bets.py explore" \
            "lb_songs:$X/lb_recording_popularity.parquet:pipeline/fetch_lb_popularity.py recording" \
            "scenes:$X/scene_bets/explore.parquet:pipeline/derive_scene_bets.py explore"; do
  name=${step%%:*}; rest=${step#*:}; output=${rest%%:*}; cmd=${rest#*:}
  if [[ -f $output ]]; then echo "-- $name already built, skipping"; continue; fi
  echo "== $name $(date +%H:%M)"
  if ! uv run python -I ${=cmd} > data/${name}_build.log 2>&1; then
    echo "-- $name FAILED $(date +%H:%M)"; grep -vE '▕|^\s+\^|^\s+~' data/${name}_build.log | tail -6; exit 1
  fi
  echo "-- $name ok $(date +%H:%M)"
done
echo "EVENING QUEUE DONE $(date +%H:%M)"
