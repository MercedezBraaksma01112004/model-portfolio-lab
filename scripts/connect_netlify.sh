#!/bin/bash
# One-time: link this folder to a Netlify site so the daily build publishes the dashboard.
# You will be asked to log in to Netlify in your browser (or create a free account), then
# to create a site. After that, every daily build deploys automatically.
set -u
cd "$(dirname "$0")/.."
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
if ! command -v npx >/dev/null 2>&1; then
  echo "Node.js is not installed. Install it from https://nodejs.org (LTS), then run this again."
  exit 1
fi
mkdir -p site
[ -f output/dashboard.html ] && cp output/dashboard.html site/index.html
echo "Step 1 of 2: log in to Netlify (a browser window will open; approve the login there)."
npx --yes netlify-cli login || exit 1
echo
echo "Step 2 of 2: create the site. Choose 'Create & configure a new site', pick your team, and give it a name"
echo "(for example model-portfolio-lab). Press return to accept defaults for anything else."
npx --yes netlify-cli deploy --prod --dir site --no-build || exit 1
echo
echo "Linked. The daily 6:30 pm build will now publish to this site automatically."
echo "Your site address is shown above as 'Website URL'."
