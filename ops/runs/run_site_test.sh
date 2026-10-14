#!/bin/bash
set -eo pipefail
cd /Users/robert/Projects/taste
uv run python -I site/build_baselines.py 2>&1 | grep -v "▕"
uv run python -I site/test_engine.py 300 2>&1 | grep -v "▕" | tail -3
echo DONE
