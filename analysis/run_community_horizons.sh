#!/bin/zsh
# After the song redo: community data for 6- and 24-month horizons, then rerun the community-leading sweeps.
cd "${0:A:h}/.."
while kill -0 11463 2>/dev/null; do sleep 30; done
for h in 6 24; do uv run python -I pipeline/derive_community.py --horizon $h > data/community_h${h}_build.log 2>&1 || echo "community h$h FAILED" >> analysis/out/cand/run.log; done
rm -rf analysis/out/cand/B_artist_h6* analysis/out/cand/B_artist_h24*
analysis/run_candidates.sh sweeps
echo "COMMUNITY HORIZONS DONE $(date +%H:%M)" >> analysis/out/cand/run.log
