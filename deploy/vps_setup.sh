#!/bin/bash
# VPS Setup: trad_bot_backtest on Ubuntu 22/24
# Run once as root, then as deploy user.

set -euo pipefail

APP_USER="deploy"
APP_DIR="/opt/trad_bot_backtest"
REPO_URL="https://github.com/eignat88/trad_bot_backtest.git"
PYTHON_VERSION="3.13"
DB_NAME="trad_bot_backtest"
DB_USER="postgres"

echo "=== 1. System packages ==="
apt update -y
apt install -y software-properties-common ufw git curl
add-apt-repository -y ppa:deadsnakes/ppa
apt install -y python${PYTHON_VERSION} python${PYTHON_VERSION}-venv python${PYTHON_VERSION}-dev postgresql postgresql-contrib

echo "=== 2. Firewall ==="
ufw allow OpenSSH
ufw allow 5432/tcp
ufw --force enable

echo "=== 3. App user ==="
if ! id "$APP_USER" &>/dev/null; then
    adduser --disabled-password --gecos "" "$APP_USER"
fi

echo "=== 4. Clone repo ==="
if [ ! -d "$APP_DIR" ]; then
    sudo -u "$APP_USER" git clone "$REPO_URL" "$APP_DIR"
fi

echo "=== 5. Python venv ==="
if [ ! -d "$APP_DIR/.venv" ]; then
    sudo -u "$APP_USER" python${PYTHON_VERSION} -m venv "$APP_DIR/.venv"
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install --upgrade pip
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt"
    sudo -u "$APP_USER" "$APP_DIR/.venv/bin/pip" install pg8000
fi

echo "=== 6. PostgreSQL database ==="
sudo -u postgres createdb "$DB_NAME" 2>/dev/null || echo "Database $DB_NAME already exists"

echo "=== 7. Apply schema ==="
sudo -u "$APP_USER" "$APP_DIR/.venv/bin/python" -m scripts.apply_schema --db-name "$DB_NAME"

echo "=== 8. Done ==="
echo "Database: $DB_NAME"
echo "App dir: $APP_DIR"
echo "Python: $APP_DIR/.venv/bin/python"
echo ""
echo "Next steps:"
echo "  1. Copy production scanner code to $APP_DIR/../trad_bot"
echo "  2. Run: cd $APP_DIR && .venv/bin/python -m scripts.backfill_edge_dataset --batch-size 200"
echo "  3. Run: cd $APP_DIR && .venv/bin/python -m scripts.validate_edge_dataset"
