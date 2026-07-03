#!/bin/bash
# Warthog Node Manager — quickstart
#
# Run on the VPS (SSH as your admin user). Requires Linux + systemd for install.
#
# Usage:
#   ./quickstart.sh install      # VPS: install + enable + start systemd units
#   ./quickstart.sh check        # VPS: verify node RPC and manager are reachable
#   ./quickstart.sh              # VPS: create venv (if needed) and run the UI
#
# Override defaults with environment variables (see README).

set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"

WARTHOG_MANAGER_DIR="${WARTHOG_MANAGER_DIR:-$DIR}"
WARTHOG_RPC="${WARTHOG_RPC:-http://127.0.0.1:3000}"
WARTHOG_SERVICE="${WARTHOG_SERVICE:-warthog-api.service}"
WARTHOG_DATA="${WARTHOG_DATA:-/home/warthognode/.warthog/defi/testnet}"
WARTHOG_MANAGER_PORT="${WARTHOG_MANAGER_PORT:-4789}"
WARTHOG_NODE_USER="${WARTHOG_NODE_USER:-warthognode}"
WARTHOG_NODE_BIN="${WARTHOG_NODE_BIN:-/home/warthognode/core/build/src/node/wart-node}"
WARTHOG_NODE_BUILD="${WARTHOG_NODE_BUILD:-/home/warthognode/core/build}"
WARTHOG_NODE_WORKDIR="${WARTHOG_NODE_WORKDIR:-$(dirname "$WARTHOG_NODE_BIN")}"

API_UNIT="/etc/systemd/system/warthog-api.service"
MANAGER_UNIT="/etc/systemd/system/warthog-manager.service"

info()  { echo "→ $*"; }
ok()    { echo "✓ $*"; }
warn()  { echo "! $*" >&2; }
die()   { echo "✗ $*" >&2; exit 1; }

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || die "Missing required command: $1"
}

sudo_cmd() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    need_cmd sudo
    sudo "$@"
  fi
}

setup_venv() {
  need_cmd python3
  if [ ! -d "$VENV" ]; then
    info "Creating Python virtual environment…"
    python3 -m venv "$VENV"
    "$VENV/bin/pip" install -q -r "$DIR/requirements.txt"
    ok "Virtual environment ready"
  else
    ok "Virtual environment exists ($VENV)"
  fi
}

rpc_check() {
  need_cmd curl
  local url="${WARTHOG_RPC%/}/chain/head"
  info "Checking node RPC at $url …"
  if curl -sf --max-time 5 "$url" >/dev/null; then
    ok "Node RPC is responding"
    return 0
  fi
  warn "Node RPC is not reachable at $WARTHOG_RPC"
  warn "Start wart-node first (e.g. sudo systemctl start $WARTHOG_SERVICE)"
  return 1
}

manager_check() {
  need_cmd curl
  local url="http://127.0.0.1:${WARTHOG_MANAGER_PORT}/"
  info "Checking manager UI at $url …"
  local code
  code="$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "$url" || true)"
  if [ "$code" = "200" ]; then
    ok "Manager UI is responding (HTTP 200)"
    return 0
  fi
  warn "Manager UI is not reachable on port $WARTHOG_MANAGER_PORT (got HTTP ${code:-none})"
  return 1
}

service_state() {
  local unit="$1"
  if systemctl is-active --quiet "$unit" 2>/dev/null; then
    echo "active"
  else
    echo "inactive"
  fi
}

service_enabled() {
  local unit="$1"
  if systemctl is-enabled --quiet "$unit" 2>/dev/null; then
    echo "enabled"
  else
    echo "disabled"
  fi
}

print_install_summary() {
  local api_state manager_state api_enabled manager_enabled
  api_state="$(service_state warthog-api.service)"
  manager_state="$(service_state warthog-manager.service)"
  api_enabled="$(service_enabled warthog-api.service)"
  manager_enabled="$(service_enabled warthog-manager.service)"

  cat <<EOF

Install complete
================

Manager (this repo)
  Checkout:     $WARTHOG_MANAGER_DIR
  Python venv:  $VENV
  Entrypoint:   $WARTHOG_MANAGER_DIR/run.sh

Node binary
  wart-node:    $WARTHOG_NODE_BIN
  Build lib:    $WARTHOG_NODE_BUILD
  Workdir:      $WARTHOG_NODE_WORKDIR
  Unix user:    $WARTHOG_NODE_USER

Node data
  WARTHOG_DATA: $WARTHOG_DATA

Systemd units
  $API_UNIT
  $MANAGER_UNIT

Services (after install)
  warthog-api.service       $api_state, $api_enabled
  warthog-manager.service   $manager_state, $manager_enabled

Endpoints (localhost only)
  Manager UI:  http://127.0.0.1:${WARTHOG_MANAGER_PORT}
  Node RPC:    ${WARTHOG_RPC}

Logs
  journalctl -u warthog-api.service -f
  journalctl -u warthog-manager.service -f

Remote access (from your laptop)
  ssh -L ${WARTHOG_MANAGER_PORT}:127.0.0.1:${WARTHOG_MANAGER_PORT} your-admin-user@your-vps
  Then open: http://127.0.0.1:${WARTHOG_MANAGER_PORT}

Edit installed units
  sudo nano $API_UNIT
  sudo nano $MANAGER_UNIT
  sudo systemctl daemon-reload
  sudo systemctl restart warthog-api.service warthog-manager.service
EOF
}

install_api_unit() {
  sudo_cmd tee "$API_UNIT" >/dev/null <<EOF
[Unit]
Description=Warthog Node (DeFi)
Documentation=https://github.com/warthog-network
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${WARTHOG_NODE_USER}
Group=${WARTHOG_NODE_USER}
WorkingDirectory=${WARTHOG_NODE_WORKDIR}
Environment=LD_LIBRARY_PATH=${WARTHOG_NODE_BUILD}
ExecStart=${WARTHOG_NODE_BIN} \\
  --minfee=0.00000001 \\
  --stratum=127.0.0.1:3457 \\
  --rpc=127.0.0.1:3000 \\
  --enable-public \\
  --testnet \\
  --enable-trades-historydb
Restart=always
RestartSec=5
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
EOF
}

install_manager_unit() {
  sudo_cmd tee "$MANAGER_UNIT" >/dev/null <<EOF
[Unit]
Description=Warthog Node Manager GUI
Documentation=https://github.com/warthog-network/node-manager-gui
After=network-online.target warthog-api.service
Wants=warthog-api.service

[Service]
Type=simple
User=root
WorkingDirectory=${WARTHOG_MANAGER_DIR}
ExecStart=${WARTHOG_MANAGER_DIR}/run.sh
Restart=on-failure
RestartSec=5
Environment=WARTHOG_RPC=${WARTHOG_RPC}
Environment=WARTHOG_SERVICE=${WARTHOG_SERVICE}
Environment=WARTHOG_DATA=${WARTHOG_DATA}
Environment=WARTHOG_MANAGER_PORT=${WARTHOG_MANAGER_PORT}

[Install]
WantedBy=multi-user.target
EOF
}

run_dev() {
  setup_venv
  rpc_check || true
  echo
  echo "Node Manager UI  → http://127.0.0.1:${WARTHOG_MANAGER_PORT}"
  echo "Node RPC target  → ${WARTHOG_RPC}"
  echo "Tunnel example   → ssh -L ${WARTHOG_MANAGER_PORT}:127.0.0.1:${WARTHOG_MANAGER_PORT} user@host"
  echo
  export WARTHOG_RPC WARTHOG_SERVICE WARTHOG_DATA WARTHOG_MANAGER_PORT
  exec "$VENV/bin/python" "$DIR/app.py"
}

install_systemd() {
  need_cmd systemctl

  info "Installing Warthog Node Manager on this host (non-interactive)…"
  setup_venv

  if [ ! -x "$WARTHOG_NODE_BIN" ]; then
    warn "wart-node binary not found or not executable: $WARTHOG_NODE_BIN"
    warn "Install will continue — fix WARTHOG_NODE_BIN and restart warthog-api.service"
  fi

  info "Writing $API_UNIT"
  install_api_unit
  info "Writing $MANAGER_UNIT"
  install_manager_unit

  info "Enabling and starting services…"
  sudo_cmd systemctl daemon-reload
  sudo_cmd systemctl enable warthog-api.service warthog-manager.service
  sudo_cmd systemctl restart warthog-api.service warthog-manager.service

  print_install_summary
  echo
  check_all || warn "Install finished, but health checks did not all pass yet"
}

check_all() {
  local ok_count=0

  if command -v systemctl >/dev/null 2>&1; then
    info "systemd status:"
    for unit in "$WARTHOG_SERVICE" warthog-manager.service; do
      if systemctl is-active --quiet "$unit" 2>/dev/null; then
        ok "$unit is active"
        ok_count=$((ok_count + 1))
      else
        warn "$unit is not active"
      fi
    done
    echo
  fi

  rpc_check && ok_count=$((ok_count + 1)) || true
  manager_check && ok_count=$((ok_count + 1)) || true

  echo
  if [ "$ok_count" -ge 2 ]; then
    ok "Quick start checks passed — open http://127.0.0.1:${WARTHOG_MANAGER_PORT}"
  else
    warn "Some checks failed; see messages above"
    return 1
  fi
}

usage() {
  cat <<EOF
Usage: $0 [command]

Run on the VPS (SSH as your admin user). install requires Linux + systemd + sudo.

Commands:
  install   Install systemd units, enable, and start (non-interactive)
  check     Verify node RPC and manager UI
  (none)    Run the manager in the foreground (development)
  help      Show this message

Environment overrides:
  WARTHOG_MANAGER_DIR   Repo checkout (default: script directory)
  WARTHOG_RPC           Node JSON-RPC URL
  WARTHOG_SERVICE       systemd unit name for the node
  WARTHOG_DATA          Node data directory
  WARTHOG_MANAGER_PORT  Manager UI port
  WARTHOG_NODE_BIN      Path to wart-node binary
  WARTHOG_NODE_BUILD    LD_LIBRARY_PATH for wart-node
  WARTHOG_NODE_WORKDIR  wart-node WorkingDirectory
  WARTHOG_NODE_USER     Unix user running wart-node
EOF
}

cmd="${1:-dev}"
case "$cmd" in
  dev|run|start|"") run_dev ;;
  check|status)     check_all ;;
  install|systemd)  install_systemd ;;
  help|-h|--help)   usage ;;
  *)                die "Unknown command: $cmd (try: $0 help)" ;;
esac