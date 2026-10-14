#!/bin/bash
set -eo pipefail
cd /Users/robert/Projects/taste
uv run --with numba python -I site/build_pack_files.py 2>&1 | grep -v "▕" | grep -v "^chunk"
uv run python -I site/compress_pack.py
uv run python -I site/check_pack.py
echo DONE
