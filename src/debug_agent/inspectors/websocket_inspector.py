"""WebSocket inspector: active connections, stats, and rooms.

Register WebSocket servers at runtime:

    from debug_agent.inspectors.websocket_inspector import register_ws_server
    register_ws_server("socketio", sio_instance)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ─────────────────────────────────────────────────────────────

_ws_servers: dict[str, Any] = {}


def register_ws_server(name: str, server: Any) -> None:
    """Register a WebSocket server (Flask-SocketIO, FastAPI WS, Django Channels)."""
    _ws_servers[name] = server


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _get_connections_from_server(name: str, server: Any) -> list[dict]:
    """Try common interfaces to extract active connections from *server*."""
    connections: list[dict] = []

    # python-socketio / Flask-SocketIO AsyncServer / Server
    try:
        # Sync Server.eio.sockets → dict of sid → engine
        eio = getattr(server, "eio", None)
        if eio is not None:
            sockets = getattr(eio, "sockets", {})
            if isinstance(sockets, dict):
                for sid, sock in sockets.items():
                    connections.append({
                        "connection_id": str(sid),
                        "remote_address": getattr(sock, "remote_addr", None),
                        "connected_since": _iso(getattr(sock, "connected_at", None)),
                        "messages_sent": getattr(sock, "upstream_messages", None),
                        "messages_received": getattr(sock, "downstream_messages", None),
                    })
    except Exception:
        pass

    # Callable interface — server returns a list of connection dicts
    if not connections and callable(server):
        try:
            result = server()
            if isinstance(result, list):
                connections = result
        except Exception:
            pass

    # Object with explicit method
    if not connections:
        for method_name in ("get_connections", "active_connections", "connections"):
            fn = getattr(server, method_name, None)
            if callable(fn):
                try:
                    result = fn()
                    if isinstance(result, list):
                        connections = result
                    elif isinstance(result, dict):
                        connections = list(result.values())
                    break
                except Exception:
                    continue

    # Dict of conn_id → conn_data
    if not connections and isinstance(server, dict):
        for cid, data in server.items():
            if isinstance(data, dict):
                connections.append({"connection_id": str(cid), **data})

    # Tag each connection with its source server
    for conn in connections:
        conn.setdefault("server", name)

    return connections


def _get_rooms_from_server(server: Any) -> dict[str, int]:
    """Try to extract room → member count from a Socket.IO server."""
    rooms: dict[str, int] = {}

    try:
        # python-socketio Server.get_rooms() or _rooms attribute
        if hasattr(server, "get_rooms"):
            for room in server.get_rooms():  # type: ignore[attr-defined]
                rooms[str(room)] = len(server.eio.sockets)  # fallback
        elif hasattr(server, "rooms"):
            raw_rooms = server.rooms
            if isinstance(raw_rooms, dict):
                for room_name, members in raw_rooms.items():
                    rooms[str(room_name)] = len(members) if hasattr(members, "__len__") else 0
            elif isinstance(raw_rooms, (list, set)):
                for r in raw_rooms:
                    rooms[str(r)] = 1
    except Exception:
        pass

    return rooms


def _iso(ts: Any) -> str | None:
    """Best-effort conversion of a timestamp to ISO string."""
    if ts is None:
        return None
    if isinstance(ts, str):
        return ts
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
    if hasattr(ts, "isoformat"):
        return ts.isoformat()
    return str(ts)


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_ws_connections",
    "List active WebSocket connections (Flask-SocketIO, FastAPI WS, Django Channels)",
)
def get_ws_connections() -> dict:
    if not _ws_servers:
        return {
            "connections": [],
            "total": 0,
            "message": "No WebSocket servers registered. Use register_ws_server(name, server).",
        }

    all_conns: list[dict] = []
    server_counts: dict[str, int] = {}
    for name, server in _ws_servers.items():
        conns = _get_connections_from_server(name, server)
        all_conns.extend(conns)
        server_counts[name] = len(conns)

    return {
        "total": len(all_conns),
        "servers": server_counts,
        "connections": all_conns,
    }


@debug_tool(
    "get_ws_stats",
    "Get WebSocket statistics: total connections, per-server counts, uptime",
)
def get_ws_stats() -> dict:
    if not _ws_servers:
        return {
            "total_servers": 0,
            "total_connections": 0,
            "message": "No WebSocket servers registered.",
        }

    all_conns: list[dict] = []
    per_server: dict[str, dict] = {}
    for name, server in _ws_servers.items():
        conns = _get_connections_from_server(name, server)
        all_conns.extend(conns)
        total_sent = sum(c.get("messages_sent") or 0 for c in conns if c.get("messages_sent"))
        total_recv = sum(c.get("messages_received") or 0 for c in conns if c.get("messages_received"))
        per_server[name] = {
            "connections": len(conns),
            "messages_sent": total_sent,
            "messages_received": total_recv,
        }

    # Earliest connection time for uptime estimate
    connect_times = [c.get("connected_since") for c in all_conns if c.get("connected_since")]
    earliest = min(connect_times) if connect_times else None

    return {
        "total_servers": len(_ws_servers),
        "total_connections": len(all_conns),
        "earliest_connection": earliest,
        "per_server": per_server,
    }


@debug_tool(
    "get_ws_rooms",
    "List Socket.IO rooms with member counts",
)
def get_ws_rooms() -> dict:
    if not _ws_servers:
        return {
            "rooms": {},
            "total_rooms": 0,
            "message": "No WebSocket servers registered.",
        }

    all_rooms: dict[str, int] = {}
    server_room_counts: dict[str, int] = {}
    for name, server in _ws_servers.items():
        rooms = _get_rooms_from_server(server)
        server_room_counts[name] = len(rooms)
        all_rooms.update(rooms)

    if not all_rooms:
        return {
            "rooms": {},
            "total_rooms": 0,
            "message": (
                "No rooms detected. Room tracking is supported for python-socketio / "
                "Flask-SocketIO servers."
            ),
            "servers_checked": list(_ws_servers.keys()),
        }

    return {
        "total_rooms": len(all_rooms),
        "rooms": dict(sorted(all_rooms.items(), key=lambda x: -x[1])),
        "per_server": server_room_counts,
    }
