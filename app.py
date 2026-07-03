#!/usr/bin/env python3
"""Warthog Node Manager — local web GUI for managing the wart-node."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shlex
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# ── Configuration ─────────────────────────────────────────────────────────────

NODE_RPC = os.environ.get("WARTHOG_RPC", "http://127.0.0.1:3000")
SERVICE_NAME = os.environ.get("WARTHOG_SERVICE", "warthog-api.service")
DATA_DIR = Path(os.environ.get("WARTHOG_DATA", "/home/warthognode/.warthog/defi/testnet"))
LOG_DIR = DATA_DIR / "logs"
PEERS_DB = DATA_DIR / "peers_v2.db3"
MANAGER_PORT = int(os.environ.get("WARTHOG_MANAGER_PORT", "4789"))
SERVICE_OVERRIDE_DIR = Path(f"/etc/systemd/system/{SERVICE_NAME}.d")

STATIC_DIR = Path(__file__).parent / "static"

MANUAL_BAN_OFFENSE = 135
DEFAULT_BAN_SECONDS = 365 * 24 * 3600

BOOL_FLAGS: list[dict[str, str]] = [
    {"key": "testnet", "flag": "--testnet", "label": "Testnet", "description": "Run on testnet"},
    {"key": "enable_public", "flag": "--enable-public", "label": "Public RPC", "description": "Expose public RPC on 0.0.0.0:3001"},
    {"key": "enable_trades_historydb", "flag": "--enable-trades-historydb", "label": "Trades history DB", "description": "Enable trades history database"},
    {"key": "enable_webrtc", "flag": "--enable-webrtc", "label": "WebRTC", "description": "Enable WebRTC peer connectivity"},
    {"key": "debug", "flag": "--debug", "label": "Debug logging", "description": "Enable verbose debug output"},
    {"key": "disable_tx_mining", "flag": "--disable-tx-mining", "label": "Disable tx mining", "description": "Do not mine transactions"},
    {"key": "isolated", "flag": "--isolated", "label": "Isolated", "description": "Disable peer connections (testing only)"},
    {"key": "temporary", "flag": "--temporary", "label": "Temporary DB", "description": "Use a temporary database (testing only)"},
    {"key": "ws_x_forwarded_for", "flag": "--ws-x-forwarded-for", "label": "X-Forwarded-For", "description": "Honor X-Forwarded-For for peer IP"},
    {"key": "ws_bind_localhost", "flag": "--ws-bind-localhost", "label": "WS localhost", "description": "Bind websocket to loopback"},
]

VALUE_FLAGS: list[dict[str, str]] = [
    {"key": "minfee", "flag": "--minfee", "label": "Min fee", "description": "Minimum mempool fee", "placeholder": "0.00000001"},
    {"key": "rpc", "flag": "--rpc", "label": "RPC bind", "description": "JSON RPC listen address", "placeholder": "127.0.0.1:3000"},
    {"key": "stratum", "flag": "--stratum", "label": "Stratum", "description": "Solo mining stratum endpoint", "placeholder": "127.0.0.1:3457"},
    {"key": "bind", "flag": "--bind", "label": "P2P bind", "description": "Peer network listen socket", "placeholder": "0.0.0.0:9286"},
    {"key": "publicrpc", "flag": "--publicrpc", "label": "Public RPC", "description": "Explicit public RPC socket", "placeholder": "0.0.0.0:3001"},
    {"key": "connect", "flag": "--connect", "label": "Seed peers", "description": "Comma-separated peer list", "placeholder": "1.2.3.4:9286"},
    {"key": "session", "flag": "--session", "label": "Session dir", "description": "Data/session directory", "placeholder": "/path/to/data"},
    {"key": "ws_port", "flag": "--ws-port", "label": "WS port", "description": "Websocket port", "placeholder": "8080"},
]

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Warthog Node Manager", version="1.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class RestartFlagsBody(BaseModel):
    bool_flags: dict[str, bool] = Field(default_factory=dict)
    value_flags: dict[str, str] = Field(default_factory=dict)


def node_request(path: str, method: str = "GET", body: bytes | None = None) -> Any:
    url = f"{NODE_RPC.rstrip('/')}{path}"
    headers = {"Accept": "application/json"}
    if body:
        headers["Content-Type"] = "application/json"
    req = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        try:
            detail = json.loads(e.read().decode())
        except Exception:
            detail = e.reason
        raise HTTPException(status_code=e.code, detail=detail) from e
    except URLError as e:
        raise HTTPException(status_code=503, detail=f"Node unreachable at {NODE_RPC}: {e.reason}") from e


def run_systemctl(action: str, *args: str) -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", action, *args],
            capture_output=True,
            text=True,
            timeout=30,
        )
        return {
            "ok": result.returncode == 0,
            "action": action,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail=f"systemctl {action} timed out")
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="systemctl not found")


def service_status() -> dict[str, Any]:
    try:
        result = subprocess.run(
            ["systemctl", "show", SERVICE_NAME, "--property=ActiveState,SubState,MainPID,ExecMainStartTimestamp"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        props: dict[str, str] = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                props[k] = v
        return {
            "service": SERVICE_NAME,
            "active": props.get("ActiveState", "unknown"),
            "sub": props.get("SubState", ""),
            "pid": int(props["MainPID"]) if props.get("MainPID", "0").isdigit() else 0,
            "started": props.get("ExecMainStartTimestamp", ""),
            "running": props.get("ActiveState") == "active",
        }
    except Exception as e:
        return {"service": SERVICE_NAME, "active": "unknown", "error": str(e), "running": False}


def read_service_unit() -> str:
    result = subprocess.run(
        ["systemctl", "cat", SERVICE_NAME],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=result.stderr.strip() or "Could not read service unit")
    return result.stdout


def parse_exec_start(unit_text: str) -> tuple[str, list[str]]:
    exec_lines = [line.strip() for line in unit_text.splitlines() if line.strip().startswith("ExecStart=")]
    if not exec_lines:
        raise HTTPException(status_code=500, detail="No ExecStart line found in service unit")

    # Drop-in overrides append ExecStart= lines; the last one wins after daemon-reload.
    raw = exec_lines[-1].split("=", 1)[1]
    parts = shlex.split(raw)
    if not parts:
        raise HTTPException(status_code=500, detail="Empty ExecStart command")
    return parts[0], parts[1:]


def parse_flag_state(argv: list[str]) -> tuple[dict[str, bool], dict[str, str]]:
    bool_state = {item["key"]: False for item in BOOL_FLAGS}
    value_state = {item["key"]: "" for item in VALUE_FLAGS}

    for arg in argv:
        for item in BOOL_FLAGS:
            if arg == item["flag"]:
                bool_state[item["key"]] = True
        for item in VALUE_FLAGS:
            prefix = f"{item['flag']}="
            if arg.startswith(prefix):
                value_state[item["key"]] = arg[len(prefix):]

    return bool_state, value_state


def build_argv(bool_flags: dict[str, bool], value_flags: dict[str, str]) -> list[str]:
    argv: list[str] = []
    for item in BOOL_FLAGS:
        if bool_flags.get(item["key"]):
            argv.append(item["flag"])
    for item in VALUE_FLAGS:
        value = (value_flags.get(item["key"]) or "").strip()
        if value:
            argv.append(f"{item['flag']}={value}")
    return argv


def ip_db_key(ip_str: str) -> int | bytes:
    ip = ipaddress.ip_address(ip_str.strip())
    if ip.version == 4:
        return int(ip)
    return ip.packed[:6]


def peers_db_connect() -> sqlite3.Connection:
    if not PEERS_DB.is_file():
        raise HTTPException(status_code=404, detail=f"Peers database not found: {PEERS_DB}")
    return sqlite3.connect(str(PEERS_DB))


def ban_peer_ip(ip_str: str) -> dict[str, Any]:
    key = ip_db_key(ip_str)
    ban_until = int(time.time()) + DEFAULT_BAN_SECONDS
    with peers_db_connect() as conn:
        conn.execute(
            "INSERT INTO bans (ip, ban_until, offense) VALUES (?, ?, ?) "
            "ON CONFLICT(ip) DO UPDATE SET ban_until=excluded.ban_until, offense=excluded.offense",
            (key, ban_until, MANUAL_BAN_OFFENSE),
        )
        conn.commit()
    return {"ip": ip_str, "banuntil": ban_until, "offense": MANUAL_BAN_OFFENSE}


def unban_peer_ip(ip_str: str) -> dict[str, Any]:
    key = ip_db_key(ip_str)
    with peers_db_connect() as conn:
        cur = conn.execute(
            "UPDATE bans SET ban_until=0, offense=0 WHERE ip=?",
            (key,),
        )
        conn.commit()
        if cur.rowcount == 0:
            raise HTTPException(status_code=404, detail=f"No ban record found for {ip_str}")
    return {"ip": ip_str, "cleared": True}


def write_service_override(binary: str, argv: list[str]) -> Path:
    SERVICE_OVERRIDE_DIR.mkdir(parents=True, exist_ok=True)
    override_path = SERVICE_OVERRIDE_DIR / "manager-flags.conf"
    command = " ".join(shlex.quote(part) for part in [binary, *argv])
    override_path.write_text(
        "[Service]\n"
        "ExecStart=\n"
        f"ExecStart={command}\n",
        encoding="utf-8",
    )
    return override_path


# ── Routes: pages ─────────────────────────────────────────────────────────────

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/config")
async def manager_config():
    rpc_host = NODE_RPC.split("://", 1)[-1]
    return {
        "manager_port": MANAGER_PORT,
        "node_rpc": NODE_RPC,
        "node_rpc_display": rpc_host,
        "service": SERVICE_NAME,
        "data_dir": str(DATA_DIR),
        "peers_db": str(PEERS_DB),
    }


# ── Routes: node API proxy ────────────────────────────────────────────────────

@app.get("/api/node/{path:path}")
async def proxy_node_get(path: str):
    return node_request(f"/{path}")


@app.api_route("/api/node/{path:path}", methods=["POST"])
async def proxy_node_post(path: str, body: dict | None = None):
    data = json.dumps(body or {}).encode()
    return node_request(f"/{path}", method="POST", body=data)


# ── Routes: dashboard aggregate ───────────────────────────────────────────────

@app.get("/api/dashboard")
async def dashboard():
    status = service_status()
    data: dict[str, Any] = {"service": status, "node": None, "error": None}

    try:
        info = node_request("/tools/info")
        head = node_request("/chain/head")
        peers_conn = node_request("/peers/connected/connection")
        mempool = node_request("/transaction/mempool")
        minfee = node_request("/transaction/minfee")

        peer_count = len(peers_conn.get("data", [])) if peers_conn.get("code") == 0 else 0
        mempool_count = len(mempool.get("data", [])) if mempool.get("code") == 0 else 0

        data["node"] = {
            "info": info.get("data"),
            "head": head.get("data"),
            "peer_count": peer_count,
            "mempool_count": mempool_count,
            "minfee": minfee.get("data"),
        }
    except HTTPException as e:
        data["error"] = e.detail

    return data


# ── Routes: service control ───────────────────────────────────────────────────

@app.get("/api/service/status")
async def get_service_status():
    return service_status()


@app.get("/api/service/flags")
async def get_service_flags():
    unit_text = read_service_unit()
    binary, argv = parse_exec_start(unit_text)
    bool_state, value_state = parse_flag_state(argv)
    return {
        "service": SERVICE_NAME,
        "binary": binary,
        "argv": argv,
        "command": " ".join(shlex.quote(part) for part in [binary, *argv]),
        "current": {"bool_flags": bool_state, "value_flags": value_state},
        "available": {"bool_flags": BOOL_FLAGS, "value_flags": VALUE_FLAGS},
        "override_dir": str(SERVICE_OVERRIDE_DIR),
    }


@app.post("/api/service/{action}")
async def control_service(action: str, body: RestartFlagsBody | None = None):
    allowed = {"start", "stop", "restart"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail=f"Action must be one of: {allowed}")

    applied_flags: dict[str, Any] | None = None
    if action == "restart" and body is not None:
        unit_text = read_service_unit()
        binary, current_argv = parse_exec_start(unit_text)
        current_bool, current_values = parse_flag_state(current_argv)

        merged_bool = {**current_bool, **body.bool_flags}
        merged_values = {**current_values}
        for key, value in body.value_flags.items():
            if value is not None:
                merged_values[key] = value.strip()

        argv = build_argv(merged_bool, merged_values)
        override_path = write_service_override(binary, argv)
        reload = run_systemctl("daemon-reload")
        if not reload["ok"]:
            raise HTTPException(status_code=500, detail=reload["stderr"] or reload["stdout"])
        applied_flags = {
            "command": " ".join(shlex.quote(part) for part in [binary, *argv]),
            "override": str(override_path),
            "bool_flags": merged_bool,
            "value_flags": merged_values,
        }

    result = run_systemctl(action, SERVICE_NAME)
    if not result["ok"]:
        raise HTTPException(status_code=500, detail=result["stderr"] or result["stdout"])
    return {**result, "status": service_status(), "applied_flags": applied_flags}


# ── Routes: logs ──────────────────────────────────────────────────────────────

@app.get("/api/logs/files")
async def list_log_files():
    files = []
    if LOG_DIR.is_dir():
        for f in sorted(LOG_DIR.iterdir()):
            if f.is_file():
                files.append({"name": f.name, "size": f.stat().st_size})
    return {"dir": str(LOG_DIR), "files": files}


@app.get("/api/logs/tail")
async def tail_log(
    file: str = Query("connections.log"),
    lines: int = Query(100, ge=1, le=2000),
):
    safe_name = Path(file).name
    log_path = LOG_DIR / safe_name
    if not log_path.is_file():
        raise HTTPException(status_code=404, detail=f"Log file not found: {safe_name}")

    try:
        result = subprocess.run(
            ["tail", "-n", str(lines), str(log_path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return {"file": safe_name, "lines": result.stdout.splitlines()}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="tail timed out")


@app.get("/api/logs/journal")
async def journal_log(lines: int = Query(100, ge=1, le=2000)):
    try:
        result = subprocess.run(
            ["journalctl", "-u", SERVICE_NAME, "-n", str(lines), "--no-pager", "-o", "short-iso"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        return {"service": SERVICE_NAME, "lines": result.stdout.splitlines()}
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=504, detail="journalctl timed out")


@app.get("/api/logs/stream")
async def stream_log(file: str = Query("connections.log")):
    safe_name = Path(file).name
    log_path = LOG_DIR / safe_name
    if not log_path.is_file():
        raise HTTPException(status_code=404, detail=f"Log file not found: {safe_name}")

    def generate():
        proc = subprocess.Popen(
            ["tail", "-f", "-n", "50", str(log_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                yield f"data: {json.dumps({'line': line.rstrip()})}\n\n"
        finally:
            proc.terminate()

    return StreamingResponse(generate(), media_type="text/event-stream")


# ── Routes: settings & peers ──────────────────────────────────────────────────

@app.post("/api/settings/minfee")
async def set_minfee(fee_e8: int = Query(..., ge=1)):
    return node_request(f"/settings/mempool/minfee/{fee_e8}")


@app.post("/api/peers/unban")
async def unban_all_peers():
    return node_request("/peers/unban")


@app.post("/api/peers/unban/{ip}")
async def unban_peer(ip: str):
    if not re.fullmatch(r"[\da-fA-F:.]+", ip):
        raise HTTPException(status_code=400, detail="Invalid IP address")
    try:
        result = unban_peer_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"code": 0, "data": result, "note": "In-memory ban cache may persist until the node restarts."}


@app.post("/api/peers/ban/{ip}")
async def ban_peer(ip: str):
    if not re.fullmatch(r"[\da-fA-F:.]+", ip):
        raise HTTPException(status_code=400, detail="Invalid IP address")
    try:
        result = ban_peer_ip(ip)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"code": 0, "data": result, "note": "Connected peers stay connected until disconnect; reconnects are blocked."}


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    print(f"Warthog Node Manager → http://127.0.0.1:{MANAGER_PORT}")
    print(f"Node RPC: {NODE_RPC}")
    uvicorn.run(app, host="127.0.0.1", port=MANAGER_PORT, log_level="info")