#!/usr/bin/env bash
# Remove the network alert cron job. Files are left in place.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/net_alert.py"

current="$(crontab -l 2>/dev/null || true)"
if ! grep -qF "$SCRIPT" <<<"$current"; then
    echo "No cron job found for $SCRIPT"
    exit 0
fi
grep -vF "$SCRIPT" <<<"$current" | grep -v '^# Network alert' | crontab -
echo "Cron job removed. Delete $DIR yourself if you no longer need it."
