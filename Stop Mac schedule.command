#!/bin/bash
# Removes the two launchd jobs that used to rebuild and publish the site from this Mac.
# The daily build now runs on GitHub Actions (see .github/workflows/daily-build.yml), so these
# jobs would only publish stale pages over the top of the cloud build.
for L in com.mercedez.portfolio-engine com.mercedez.portfolio-engine.changes; do
  launchctl bootout "gui/$(id -u)/$L" 2>/dev/null && echo "stopped $L" || echo "$L was not running"
  rm -f "$HOME/Library/LaunchAgents/$L.plist" && echo "removed $L.plist"
done
echo "Done. The site is now rebuilt by GitHub Actions each weekday evening."
read -n 1 -s -r -p "Press any key to close"
