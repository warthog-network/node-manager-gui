# Warthog Node Manager

A local web GUI for operating a `wart-node` systemd service: dashboard, peers, mempool, logs, service control, and fee settings.

## What runs where

Two separate systemd services work together:

| Service | Unit file | Program | Port | Role |
|---------|-----------|---------|------|------|
| **Node** | `warthog-api.service` | `wart-node` | RPC `3000`, stratum `3457` | Syncs chain, peers, mempool — the actual blockchain node |
| **Manager** | `warthog-manager.service` | `app.py` (this repo) | `4789` | Web dashboard that monitors and controls the node |

```text
Browser  →  :4789  warthog-manager  →  :3000  warthog-api (wart-node)  →  P2P network
```

The manager never replaces the node — it only talks to it over JSON-RPC and `systemctl`.

## Repository

```text
https://github.com/warthog-network/node-manager-gui
```

On this VPS the single canonical checkout is:

```text
/home/warthognode/node-manager
```

That path is the git repo, runtime files, and what `warthog-manager.service` executes. Update with:

```bash
cd /home/warthognode/node-manager
git pull
sudo systemctl restart warthog-manager.service
```

---

## Full setup (VPS)

Step-by-step from a fresh server with a built `wart-node` binary.

### Prerequisites

- Linux with **systemd**
- **Python 3.10+**
- `git`, `systemctl`, `journalctl`
- A built `wart-node` binary (e.g. under `/home/warthognode/core/build/src/node/wart-node`)
- A dedicated **non-login** Unix user for the node (e.g. `warthognode`)
- An admin SSH account for server access (e.g. `root` or your VPS user) — **not** `warthognode`

### Step 1 — Node user and data directory

Create a service account that runs `wart-node` but cannot SSH in (no shell, no password):

```bash
sudo groupadd -f warthognode
sudo useradd -r -g warthognode -d /home/warthognode -s /bin/false warthognode
sudo mkdir -p /home/warthognode
sudo chown -R warthognode:warthognode /home/warthognode

# First run of wart-node creates data under ~/.warthog/...
# Default testnet path used by this project:
#   /home/warthognode/.warthog/defi/testnet
```

`warthognode` is for systemd only. Use your normal admin account for SSH and for the tunnel in Step 5.

Ensure the `warthognode` user owns its home and can execute `wart-node`:

```bash
sudo -u warthognode test -x /home/warthognode/core/build/src/node/wart-node && echo OK
```

### Step 2 — Install `warthog-api.service` (the node)

Copy the example unit and edit paths/flags for your build:

```bash
cd /home/warthognode/node-manager
sudo cp warthog-api.service.example /etc/systemd/system/warthog-api.service
sudo nano /etc/systemd/system/warthog-api.service
```

**Must match your server:**

| Field | Example on this VPS |
|-------|---------------------|
| `User` / `Group` | `warthognode` |
| `WorkingDirectory` | `/home/warthognode/core/build/src/node` |
| `Environment=LD_LIBRARY_PATH` | `/home/warthognode/core/build` |
| `ExecStart` | Full path to `wart-node` + flags |

**Important flags:**

| Flag | Purpose |
|------|---------|
| `--rpc=127.0.0.1:3000` | JSON-RPC for the manager — keep on **localhost** |
| `--stratum=127.0.0.1:3457` | Solo mining stratum |
| `--minfee=0.00000001` | Mempool minimum fee |
| `--testnet` | Testnet (remove for mainnet) |
| `--enable-public` | Public RPC on `0.0.0.0:3001` |
| `--enable-trades-historydb` | Trade history database |

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable warthog-api.service
sudo systemctl start warthog-api.service
sudo systemctl status warthog-api.service
```

Verify RPC responds:

```bash
curl -s http://127.0.0.1:3000/chain/head | head -c 200
```

Follow logs:

```bash
journalctl -u warthog-api.service -f
```

### Step 3 — Clone the Node Manager

```bash
sudo -u warthognode git clone https://github.com/warthog-network/node-manager-gui.git /home/warthognode/node-manager
cd /home/warthognode/node-manager
```

Create the Python venv (also done automatically by `run.sh` on first run):

```bash
./run.sh
# Ctrl+C after confirming it starts — we'll use systemd next
```

Or install deps only:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Step 4 — Install `warthog-manager.service` (the GUI)

```bash
cd /home/warthognode/node-manager
sudo cp warthog-manager.service.example /etc/systemd/system/warthog-manager.service
sudo nano /etc/systemd/system/warthog-manager.service
```

**Environment variables** (in the unit file or override):

| Variable | Default | Description |
|----------|---------|-------------|
| `WARTHOG_RPC` | `http://127.0.0.1:3000` | Node JSON-RPC — must match `wart-node --rpc` |
| `WARTHOG_SERVICE` | `warthog-api.service` | systemd unit name the GUI controls |
| `WARTHOG_DATA` | `/home/warthognode/.warthog/defi/testnet` | Node data dir (logs, peers DB) |
| `WARTHOG_MANAGER_PORT` | `4789` | Web UI listen port |

Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable warthog-manager.service
sudo systemctl start warthog-manager.service
sudo systemctl status warthog-manager.service
```

Open locally on the VPS: http://127.0.0.1:4789

### Step 5 — Remote access (SSH tunnel)

The manager binds to localhost only. From your laptop, SSH as your **admin** user (the account you use to manage the VPS — not `warthognode`):

```bash
ssh -L 4789:127.0.0.1:4789 root@your-vps
# or: ssh -L 4789:127.0.0.1:4789 your-admin-user@your-vps
```

Then open: http://127.0.0.1:4789

Keep tunnel alive without a shell:

```bash
ssh -N -L 4789:127.0.0.1:4789 root@your-vps
```

The tunnel forwards port 4789 on your machine to the manager on the VPS. You do not need to log in as `warthognode`.

### Step 6 — Verify both services

```bash
systemctl is-active warthog-api.service warthog-manager.service
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:4789/
```

Expected: both `active`, HTTP `200`.

---

## Quick start (development / foreground)

Without systemd — useful for local testing:

```bash
cd node-manager
./run.sh
```

Then open: http://127.0.0.1:4789

Override env vars inline:

```bash
WARTHOG_RPC=http://127.0.0.1:3000 \
WARTHOG_DATA=/home/warthognode/.warthog/defi/testnet \
./run.sh
```

---

## Manager ↔ node integration

### Flag changes from the GUI

On the **Service** page you can toggle `wart-node` flags and click **Restart with Options**. That writes a systemd drop-in:

```text
/etc/systemd/system/warthog-api.service.d/manager-flags.conf
```

The drop-in overrides `ExecStart` only; your base `warthog-api.service` file stays the manual baseline.

Revert GUI-driven flag changes:

```bash
sudo rm -rf /etc/systemd/system/warthog-api.service.d
sudo systemctl daemon-reload
sudo systemctl restart warthog-api.service
```

Requires permission to manage systemd (manager runs as `root`).

### Service restart with flags (GUI)

1. See the current `ExecStart` command and active flags
2. Toggle boolean flags (`--enable-public`, `--testnet`, …)
3. Edit value flags (`--minfee`, `--rpc`, `--stratum`, …)
4. **Restart with Options** — writes drop-in, `daemon-reload`, restarts `warthog-api`

---

## Features

- **Dashboard** — chain head, sync, hashrate, peers, mempool, min fee, uptime
- **Peers** — connected list, ban individual IPs, banned list with per-IP unban, unban all
- **Mempool** — pending transactions
- **Logs** — tail log files or journal, live stream
- **Service** — start/stop/restart; view/toggle `wart-node` flags
- **Settings** — adjust mempool minimum fee live

## Peer ban / unban notes

| Action | How it works |
|--------|----------------|
| **Unban all** | Calls node RPC `GET /peers/unban` — clears DB and in-memory cache immediately |
| **Unban one** | Clears that IP in the peers database |
| **Ban one** | Writes a ban record to the peers database |

Individual unban/ban updates the SQLite peers DB. The node's in-memory ban cache may still block an IP until you **Unban all** or restart the node. Connected peers are not kicked instantly by a ban; they are blocked on reconnect.

## Requirements

- Python 3.10+
- `systemctl`, `journalctl`, `tail`
- Running `wart-node` with RPC enabled
- Read access to node log/data directories

## Security

- Run `wart-node` as a non-login service user (`/bin/false`, no password) — SSH with your admin account instead
- Do **not** expose port **4789** (manager) or **3000** (node RPC) to the public internet
- Use SSH tunnels or a VPN for remote access
- Node RPC is not authenticated — keep `--rpc` on `127.0.0.1` or behind a firewall
- Public RPC (`--enable-public` / port 3001) is separate; lock down as needed for your deployment