#!/bin/zsh
# Usage: ops/ingest.sh start|stop|status
set -e
LABEL=com.robert.taste-ingest
PLIST=~/Library/LaunchAgents/$LABEL.plist
ROOT="${0:A:h}/.."
case "$1" in
  start)
    mkdir -p "$ROOT/data/mlhd/_logs"
    cp "$ROOT/ops/$LABEL.plist" "$PLIST"
    launchctl bootstrap gui/$(id -u) "$PLIST" && echo "started" ;;
  stop)
    launchctl bootout gui/$(id -u)/$LABEL && rm -f "$PLIST" && echo "stopped (progress is kept; start resumes)" ;;
  status|"")
    launchctl print gui/$(id -u)/$LABEL 2>/dev/null | grep -E '^\s+(state|pid|last exit code)' || echo "service not loaded"
    /opt/homebrew/bin/uv run --project "$ROOT" python -I "$ROOT/pipeline/ingest_status.py" "$ROOT/data/mlhd" ;;
esac
