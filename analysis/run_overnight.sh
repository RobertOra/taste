#!/bin/zsh
# Overnight chain: after the evening builds (pid 97366) -> main candidates -> sealed building blocks -> sweeps
# -> "is it just X" variants. Keeps the Mac awake (on power) while running.
cd "${0:A:h}/.."
while kill -0 97366 2>/dev/null; do sleep 30; done
grep -q "EVENING QUEUE DONE" data/evening_queue.log || { echo "evening builds failed; stopping $(date +%H:%M)"; exit 1; }
echo "== main candidates $(date +%H:%M)";  analysis/run_candidates.sh main
echo "== sealed building blocks $(date +%H:%M)"; analysis/run_sealed_build.sh || echo "sealed build failed"
echo "== sweeps $(date +%H:%M)"; analysis/run_candidates.sh sweeps
echo "== is-it-just-X $(date +%H:%M)"; analysis/run_candidates.sh justx
echo "OVERNIGHT DONE $(date +%H:%M)"
