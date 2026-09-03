#!/bin/bash
# Quick status check for edge backfill on VPS

APP_DIR="/opt/trad_bot_backtest"
VENV="$APP_DIR/.venv/bin/python"

cd "$APP_DIR"

echo "=== Backfill progress ==="
if [ -f /tmp/edge_backfill.log ]; then
    grep "processed:" /tmp/edge_backfill.log | tail -5
    tail -1 /tmp/edge_backfill.log
else
    echo "No log found at /tmp/edge_backfill.log"
fi

echo ""
echo "=== Screen session ==="
screen -list 2>/dev/null || echo "No screen sessions"

echo ""
echo "=== Dataset coverage ==="
$VENV -m scripts.validate_edge_dataset --min-coverage 0.0001 2>&1 || true
