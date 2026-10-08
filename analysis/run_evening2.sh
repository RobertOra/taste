#!/bin/zsh
# After the evening queue: rebuild scene bets with all outcomes (needs community homes), then song popularity.
cd "${0:A:h}/.."
while kill -0 93892 2>/dev/null; do sleep 20; done
echo "== scenes $(date +%H:%M)"
uv run python -I pipeline/derive_scene_bets.py explore 2>&1 | grep -v '▕' | tail -10 || echo FAILED
echo "SCENES DONE $(date +%H:%M)"
