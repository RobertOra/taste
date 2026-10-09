#!/bin/zsh
# Rerun song mains (collapsed), then the "is it just X" variants, then the settings sweeps.
cd "${0:A:h}/.."
analysis/run_candidates.sh main
analysis/run_candidates.sh justx
analysis/run_candidates.sh sweeps
echo "REST DONE $(date +%H:%M)" >> analysis/out/cand/run.log
