#!/bin/bash
cd "$(dirname "$0")/portfolio-engine" || { echo "portfolio-engine folder not found next to this file"; read -p "Press return to close"; exit 1; }
bash scripts/connect_netlify.sh
echo; read -p "Press return to close"
