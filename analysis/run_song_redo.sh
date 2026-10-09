#!/bin/zsh
# After the variants and sweeps finish, rerun the song main candidates with the finer song-age control.
cd "${0:A:h}/.."
while kill -0 11281 2>/dev/null; do sleep 30; done
for c in A_song_main B_song_main C_lb_song_main D_song_main; do mv analysis/out/cand/$c analysis/out/cand/_superseded/${c}_coarse_age 2>/dev/null; done
analysis/run_candidates.sh main
echo "SONG REDO DONE $(date +%H:%M)" >> analysis/out/cand/run.log
