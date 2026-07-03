#!/bin/bash
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"

if [ ! -d "$VENV" ]; then
  echo "Creating virtual environment…"
  python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q -r "$DIR/requirements.txt"
fi

export WARTHOG_RPC="${WARTHOG_RPC:-http://127.0.0.1:3000}"
export WARTHOG_SERVICE="${WARTHOG_SERVICE:-warthog-api.service}"
export WARTHOG_DATA="${WARTHOG_DATA:-/home/warthognode/.warthog/defi/testnet}"
export WARTHOG_MANAGER_PORT="${WARTHOG_MANAGER_PORT:-4789}"

echo "Node Manager UI  → http://127.0.0.1:${WARTHOG_MANAGER_PORT}"
echo "Node RPC target  → ${WARTHOG_RPC}"
echo "Tunnel example   → ssh -L ${WARTHOG_MANAGER_PORT}:127.0.0.1:${WARTHOG_MANAGER_PORT} user@host"

exec "$VENV/bin/python" "$DIR/app.py"