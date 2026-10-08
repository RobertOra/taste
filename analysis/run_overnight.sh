#!/bin/zsh
# Full chain: evening builds (songs, song popularity, scenes) -> main candidates -> sealed building blocks
# -> sweeps -> "is it just X" variants. Keeps the Mac awake (on power) while running.
cd "${0:A:h}/.."
echo "== evening builds $(date +%H:%M)"
analysis/run_evening.sh > data/evening_queue.log 2>&1
grep -q "EVENING QUEUE DONE" data/evening_queue.log || { echo "evening builds failed; stopping $(date +%H:%M)"; exit 1; }
echo "== main candidates $(date +%H:%M)";  analysis/run_candidates.sh main
echo "== sealed building blocks $(date +%H:%M)"; analysis/run_sealed_build.sh || echo "sealed build failed"
echo "== sweeps $(date +%H:%M)"; analysis/run_candidates.sh sweeps
echo "== is-it-just-X $(date +%H:%M)"; analysis/run_candidates.sh justx
echo "OVERNIGHT DONE $(date +%H:%M)"
