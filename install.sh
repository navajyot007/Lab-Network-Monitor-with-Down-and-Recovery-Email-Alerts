#!/usr/bin/env bash
# Set up the network alert on Linux or macOS.
#
# First run:  creates config.env from the example and stops so you can edit it.
# Second run: checks the settings, sends a test mail, and adds the cron job.
#
# Usage: ./install.sh [minutes]     default schedule is every 5 minutes
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="$DIR/net_alert.py"
CONFIG="$DIR/config.env"
EVERY="${1:-5}"

if [[ ! "$EVERY" =~ ^[0-9]+$ ]] || (( EVERY < 1 || EVERY > 59 )); then
    echo "Schedule must be a number of minutes from 1 to 59."
    exit 1
fi

missing=()
for cmd in python3 ping crontab; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
done
if (( ${#missing[@]} )); then
    echo "Missing: ${missing[*]}"
    echo "Ubuntu/Debian: sudo apt install python3 iputils-ping cron"
    echo "macOS: python3 comes with Xcode tools (xcode-select --install)"
    exit 1
fi

chmod 755 "$SCRIPT"
mkdir -p "$DIR/state"

if [[ ! -f "$CONFIG" ]]; then
    cp "$DIR/config.env.example" "$CONFIG"
    chmod 600 "$CONFIG"
    echo "Created $CONFIG"
    echo "Edit it now. Change every line marked CHANGE, then run ./install.sh again."
    exit 0
fi
chmod 600 "$CONFIG"

if grep -q '^MAIL_METHOD=mutt' "$CONFIG" && ! command -v mutt >/dev/null 2>&1; then
    echo "MAIL_METHOD=mutt but mutt is not installed. Install mutt or use MAIL_METHOD=smtp."
    exit 1
fi

echo "Sending a test mail..."
if ! python3 "$SCRIPT" --mail-test; then
    echo "The test mail failed. Check $DIR/state/alerts.log and config.env."
    exit 1
fi

echo "Running one check..."
python3 "$SCRIPT"
python3 "$SCRIPT" --status

line="*/$EVERY * * * * /usr/bin/env python3 $SCRIPT"
current="$(crontab -l 2>/dev/null || true)"
if grep -qF "$SCRIPT" <<<"$current"; then
    current="$(grep -vF "$SCRIPT" <<<"$current" | grep -v '^# Network alert' || true)"
fi
printf '%s\n# Network alert: ping TARGETS and mail on down/up.\n%s\n' "$current" "$line" \
    | sed '/^$/N;/^\n$/D' | crontab -

echo "Cron job installed:"
crontab -l | grep -F "$SCRIPT"
echo "Log: tail -f $DIR/state/alerts.log"
