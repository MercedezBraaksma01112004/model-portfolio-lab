#!/bin/bash
# Hourly: if the website has queued changes, run a full build and publish. Called by launchd.
cd "$(dirname "$0")/.."
SITE=$(cat .netlify/site_url 2>/dev/null); [ -z "$SITE" ] && exit 0
N=$(curl -s --max-time 20 "$SITE/.netlify/functions/changes" | python3 -c "import sys,json; print(len(json.load(sys.stdin).get('pending',[])))" 2>/dev/null || echo 0)
if [ "${N:-0}" -gt 0 ]; then
  echo "=== $(date '+%Y-%m-%d %H:%M') $N website change(s) queued; rebuilding"
  bash scripts/run_build.sh
fi
