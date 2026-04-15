#!/bin/bash
set -e

INSTANCE_NAME="${INSTANCE_NAME:-banana-bot}"
echo "[${INSTANCE_NAME}] Starting..."

# Seed /root on first start
if [ ! -f "/root/.initialized" ]; then
    echo "[${INSTANCE_NAME}] First-time setup: seeding /root..."
    cp -a /root-seed/. /root/
    mkdir -p /root/workspace /root/uploads
    touch /root/.initialized
    echo "[${INSTANCE_NAME}] Done."
fi

# Seed source code to repo volume if empty
APP_SOURCE_DIR="${APP_SOURCE_DIR:-/app/src}"
if [ "$APP_SOURCE_DIR" != "/app/src" ] && [ ! -f "${APP_SOURCE_DIR}/__init__.py" ] && [ ! -f "${APP_SOURCE_DIR}/main.py" ]; then
    echo "[${INSTANCE_NAME}] Seeding source code to ${APP_SOURCE_DIR}..."
    mkdir -p "$(dirname ${APP_SOURCE_DIR})"
    cp -a /app/src-seed "${APP_SOURCE_DIR}"
    echo "[${INSTANCE_NAME}] Source code seeded."
fi

# Set GH_TOKEN from GH_PAT for gh CLI
export GH_TOKEN="${GH_PAT:-}"
export PLAYWRIGHT_BROWSERS_PATH=/root/.playwright

# Check Claude Code auth
if claude auth status > /dev/null 2>&1; then
    echo "[${INSTANCE_NAME}] Claude Code: authenticated"
else
    echo "[${INSTANCE_NAME}] Claude Code: NOT authenticated"
    echo "[${INSTANCE_NAME}] Run: docker compose exec backend claude login"
fi

# Check gh auth
if [ -n "$GH_TOKEN" ]; then
    echo "[${INSTANCE_NAME}] GitHub CLI: token set"
else
    echo "[${INSTANCE_NAME}] GitHub CLI: no token (optional)"
fi

echo "[${INSTANCE_NAME}] Starting bot..."

# Use APP_SOURCE_DIR to determine where to run from
if [ "$APP_SOURCE_DIR" != "/app/src" ] && [ -f "${APP_SOURCE_DIR}/main.py" ]; then
    PARENT_DIR="$(dirname ${APP_SOURCE_DIR})"
    cd "${PARENT_DIR}"
    exec python3 -m src.main
else
    exec python3 -m src.main
fi
