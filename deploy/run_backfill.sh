#!/bin/bash
# Run edge backfill inside screen session
# Usage: bash run_backfill.sh [--symbol SYMBOL] [--batch-size N]

set -euo pipefail

APP_DIR="/opt/trad_bot_backtest"
VENV="$APP_DIR/.venv/bin/python"
SCREEN_NAME="edge_backfill"

cd "$APP_DIR"

if screen -list | grep -q "$SCREEN_NAME"; then
    echo "Screen session '$SCREEN_NAME' already running. Attach with: screen -r $SCREEN_NAME"
    exit 1
fi

echo "Starting backfill in screen session '$SCREEN_NAME'..."
echo "Attach: screen -r $SCREEN_NAME"
echo "Detach: Ctrl+A then D"
echo ""

screen -dmS "$SCREEN_NAME" bash -c "
cd $APP_DIR
$VENV -m scripts.backfill_edge_dataset --batch-size 200 $@ 2>&1 | tee /tmp/edge_backfill.log
echo 'Backfill finished at $(date)' >> /tmp/edge_backfill.log
echo 'DONE' >> /tmp/edge_backfill.log
"

echo "Screen started. Monitor with: tail -f /tmp/edge_backfill.log"
echo "Check status: grep 'processed:' /tmp/edge_backfill.log | tail -5"
