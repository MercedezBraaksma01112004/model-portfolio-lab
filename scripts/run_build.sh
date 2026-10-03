#!/bin/bash
# Daily build. Called by launchd (see install_mac.sh). Refreshes prices, rebuilds every
# portfolio, then publishes the dashboard to Netlify if a site has been linked (see
# "Connect Netlify.command" / scripts/connect_netlify.sh).
set -u
cd "$(dirname "$0")/.."
PY=".venv/bin/python"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
echo "=== $(date '+%Y-%m-%d %H:%M') build start"
"$PY" scripts/sync_changes.py
if [ ! -f data/cache/search_index.json ] || [ -n "$(find data/cache/search_index.json -mtime +7 2>/dev/null)" ]; then "$PY" scripts/build_search_index.py; fi
"$PY" -m portfolio_engine --refresh build || { echo "build failed"; exit 1; }
mkdir -p site && cp output/dashboard.html site/index.html && cp output/builder.html site/builder.html
"$PY" scripts/quality_report.py >/dev/null && cp output/quality_review.html site/quality.html
cp output/model_portfolios_latest.xlsx site/model_portfolios_latest.xlsx
"$PY" scripts/build_listing_data.py >/dev/null 2>&1 || echo "listing data build failed (the builder page falls back to the live function)"
[ -f .netlify/auth_token ] && export NETLIFY_AUTH_TOKEN="$(cat .netlify/auth_token)"
if [ -f .netlify/state.json ] && command -v npx >/dev/null 2>&1; then
  if npx --yes netlify-cli deploy --prod --dir site --functions netlify/functions --no-build >site/deploy.log 2>&1; then
    echo "published to Netlify: $(grep -Eo 'https://[^ ]+' site/deploy.log | grep -v 'app.netlify' | head -1)"
  else
    echo "Netlify publish failed (see site/deploy.log)"
  fi
fi
echo "=== $(date '+%Y-%m-%d %H:%M') build done"
