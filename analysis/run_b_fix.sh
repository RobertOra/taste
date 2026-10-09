#!/bin/zsh
# After the main rebuild: community prior popularity for songs/scenes, then redo community-leading for songs
# and scenes (main + variants + sweeps) with that control.
cd "${0:A:h}/.."
while kill -0 27504 2>/dev/null; do sleep 20; done
uv run python -I pipeline/derive_comm_prior.py explore > data/comm_prior_build.log 2>&1 || { echo "comm prior FAILED" >> analysis/out/cand/run.log; exit 1; }
mkdir -p analysis/out/cand/_superseded
for d in analysis/out/cand/B_song_* analysis/out/cand/B_scene_*; do
  [[ -d $d ]] && rm -rf analysis/out/cand/_superseded/$(basename $d)_no_comm_prior && mv $d analysis/out/cand/_superseded/$(basename $d)_no_comm_prior
done
rm -f analysis/out/cand/B_song_*.log analysis/out/cand/B_scene_*.log
analysis/run_candidates.sh main; analysis/run_candidates.sh justx; analysis/run_candidates.sh sweeps
echo "B FIX DONE $(date +%H:%M)" >> analysis/out/cand/run.log
