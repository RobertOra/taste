#!/bin/zsh
# Sealed-half building blocks only (no models are scored, no results are looked at). One job at a time.
cd "${0:A:h}/.."
for step in "uyf_explore pipeline/derive_user_year_features.py explore" "bets pipeline/derive_bets.py sealed" "features pipeline/derive_user_features.py sealed" \
            "market pipeline/derive_market.py sealed" "community pipeline/derive_community.py --horizon 12 --half sealed" \
            "songs pipeline/derive_song_bets.py sealed" "scenes pipeline/derive_scene_bets.py sealed" \
            "lb_songs pipeline/fetch_lb_popularity.py recording" "uyf pipeline/derive_user_year_features.py sealed"; do
  name=${step%% *}; cmd=${step#* }
  echo "== sealed $name $(date +%H:%M)"
  if ! uv run python -I ${=cmd} > data/sealed_${name}_build.log 2>&1; then
    echo "-- sealed $name FAILED $(date +%H:%M)"; exit 1
  fi
  echo "-- sealed $name ok $(date +%H:%M)"
done
echo "SEALED BUILD DONE $(date +%H:%M)"
