#!/bin/bash
set -eo pipefail
cd /Users/robert/Projects/taste
uv run python -I site/build_pack_ref.py 2>&1 | grep -v "▕" | grep -v " batch "
uv run python -I site/build_pack_scores.py 2>&1 | grep -v "▕"
uv run python -I site/build_pack_meta.py 2>&1 | grep -v "▕"
echo DONE
