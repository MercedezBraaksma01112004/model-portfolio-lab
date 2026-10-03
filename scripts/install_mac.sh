#!/bin/bash
# One-time macOS setup: virtual environment, dependencies, a launchd job that rebuilds every
# weekday at 6:30 pm (after the ASX close), and a first build.
#   bash scripts/install_mac.sh
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
LABEL="com.mercedez.portfolio-engine"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

echo "Project: $ROOT"
if ! command -v python3 >/dev/null; then
  echo "python3 not found. Install the Xcode command line tools (xcode-select --install) and rerun."; exit 1
fi
python3 --version
if [ ! -x .venv/bin/python ]; then
  echo "Creating virtual environment"
  python3 -m venv .venv
fi
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt
echo "Dependencies installed"
chmod +x scripts/run_build.sh
mkdir -p output data/cache data/prices "$HOME/Library/LaunchAgents"

cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string>
    <string>$ROOT/scripts/run_build.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartCalendarInterval</key><array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>18</integer><key>Minute</key><integer>30</integer></dict>
  </array>
  <key>StandardOutPath</key><string>$ROOT/output/build.log</string>
  <key>StandardErrorPath</key><string>$ROOT/output/build.log</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
</dict></plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "launchd job installed: $LABEL (weekdays 18:30). Log: output/build.log"

# Hourly check for changes queued on the website.
LABEL2="$LABEL.changes"
PLIST2="$HOME/Library/LaunchAgents/$LABEL2.plist"
cat > "$PLIST2" <<EOF2
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL2</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$ROOT/scripts/check_changes.sh</string></array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>StartInterval</key><integer>3600</integer>
  <key>StandardOutPath</key><string>$ROOT/output/build.log</string>
  <key>StandardErrorPath</key><string>$ROOT/output/build.log</string>
  <key>EnvironmentVariables</key><dict><key>PATH</key><string>/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin</string></dict>
</dict></plist>
EOF2
launchctl bootout "gui/$(id -u)/$LABEL2" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST2"
echo "launchd job installed: $LABEL2 (hourly check for website changes)"
[ -d node_modules/@netlify/blobs ] || (command -v npm >/dev/null && npm install --silent --no-audit --no-fund >/dev/null 2>&1 && echo "Netlify function dependencies installed")

echo "Running first build now"
bash scripts/run_build.sh
echo "Done. Outputs in $ROOT/output"
