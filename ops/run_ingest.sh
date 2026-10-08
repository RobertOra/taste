#!/bin/zsh
# Entry point for the launchd job: keeps the Mac awake (on AC power) only while ingesting.
cd "${0:A:h}/.." || exit 1
exec /usr/bin/caffeinate -i -s /opt/homebrew/bin/uv run python -I pipeline/mlhd_ingest.py --workers "${TASTE_WORKERS:-3}"
