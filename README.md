# Warthog Node Manager

A local web GUI for operating a `wart-node` systemd service: dashboard, peers, mempool, logs, service control, and fee settings.

The manager binds to **127.0.0.1:4789** by default. The node JSON-RPC API (what the manager talks to) is separate, typically **127.0.0.1:3000**.

## Quick start (on the node server)

```bash
cd node-manager
./run.sh
```

Then open: http://127.0.0.1:4789

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WARTHOG_RPC` | `http://127.0.0.1:3000` | Node JSON-RPC endpoint |
| `WARTHOG_SERVICE` | `warthog-api.service` | systemd unit name |
| `WARTHOG_DATA` | `/home/warthognode/.warthog/defi/testnet` | Node data directory |
| `WARTHOG_MANAGER_PORT` | `4789` | Manager web UI port |

Example with custom paths:

```bash
WARTHOG_RPC=http://127.0.0.1:3000 \
WARTHOG_DATA=/home/warthognode/.warthog/defi/testnet \
./run.sh
```

Restart the manager after changing env vars:

```bash
pkill -f "node-manager/app.py" || true
WARTHOG_RPC=http://127.0.0.1:3000 ./run.sh
```

## Remote access via SSH tunnel

The manager only listens on localhost. To use it from your laptop, forward port **4789**:

```bash
ssh -L 4789:127.0.0.1:4789 user@your-node-server
```

Then open on your laptop: http://127.0.0.1:4789

### Optional: forward node RPC too

Normally you only need the manager tunnel — the manager reaches the node RPC locally on the server. If you want direct RPC access from your laptop (curl, scripts, etc.), add a second forward:

```bash
ssh -L 4789:127.0.0.1:4789 -L 3000:127.0.0.1:3000 user@your-node-server
```

- http://127.0.0.1:4789 → Node Manager GUI
- http://127.0.0.1:3000 → wart-node JSON-RPC (browser shows endpoint list)

### Keep tunnel alive

```bash
ssh -N -L 4789:127.0.0.1:4789 user@your-node-server
```

`-N` skips a remote shell (tunnel only). Add `-f` to background it.

### VS Code / Cursor Remote

If you are already connected via Remote-SSH, port 4789 is often auto-forwarded. Check the **Ports** panel and open the forwarded URL.

## Features

- **Dashboard** — chain head, sync, hashrate, peers, mempool, min fee, uptime
- **Peers** — connected list, ban individual IPs, banned list with per-IP unban, unban all
- **Mempool** — pending transactions
- **Logs** — tail log files or journal, live stream
- **Service** — start/stop/restart; view current `wart-node` flags; toggle options (e.g. `--enable-public`, `--testnet`) and restart with a systemd drop-in override
- **Settings** — adjust mempool minimum fee live

## Peer ban / unban notes

| Action | How it works |
|--------|----------------|
| **Unban all** | Calls node RPC `GET /peers/unban` — clears DB and in-memory cache immediately |
| **Unban one** | Clears that IP in the peers database |
| **Ban one** | Writes a ban record to the peers database |

Individual unban/ban updates the SQLite peers DB. The node's in-memory ban cache may still block an IP until you **Unban all** or restart the node. Connected peers are not kicked instantly by a ban; they are blocked on reconnect.

## Service restart with flags

On the **Service** page you can:

1. See the current `ExecStart` command and all active flags
2. Toggle boolean flags (`--enable-public`, `--testnet`, etc.)
3. Edit value flags (`--minfee`, `--rpc`, `--stratum`, …)
4. Click **Restart with Options** — writes `/etc/systemd/system/<service>.d/manager-flags.conf`, runs `daemon-reload`, then restarts

Requires permission to manage systemd (the manager process typically runs as root).

## Requirements

- Python 3.10+
- `systemctl`, `journalctl`, `tail`
- Running `wart-node` with RPC enabled
- Read access to node log/data directories

## Security

- Do **not** expose port 4789 or the node RPC port (3000) to the public internet
- Use SSH tunnels or a VPN for remote access
- The node RPC endpoint is not authenticated — keep it on localhost or behind a firewall