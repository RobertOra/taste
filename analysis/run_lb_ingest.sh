#!/bin/bash
# ListenBrainz overnight ingest (streams ~236 GB, keeps ~15-35 GB of weekly tables in data/lb). Safe to re-run: finished
# months are skipped. Log: data/lb_ingest.log. Stop with: pkill -f lb_ingest.py
cd /Users/robert/Projects/taste
uv run python -I pipeline/lb_ingest.py
echo "exit code $?"
