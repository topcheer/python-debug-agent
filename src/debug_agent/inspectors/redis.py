"""Redis inspector: connection pool stats, INFO, latency, and CONFIG for redis-py clients.

Register a redis-py client at runtime so the inspectors can reach it:

    from debug_agent.inspectors.redis import register_redis_client
    register_redis_client("default", redis_client)

All tools degrade gracefully when redis-py is not installed or no client is
registered.
"""

from __future__ import annotations

import time
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration mechanism ──────────────────────────────────────────────────

_registered_redis_clients: dict[str, Any] = {}


def register_redis_client(name: str, client: Any) -> None:
    """Register a redis-py client under a name so the inspectors can find it."""
    _registered_redis_clients[name] = client


def _get_clients() -> dict[str, Any]:
    """Return the registered clients dict (empty when redis-py is absent)."""
    return _registered_redis_clients


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _redis_available() -> bool:
    try:
        import redis  # noqa: F401
        return True
    except ImportError:
        return False


def _coerce_int(value: Any, default: int = 10) -> int:
    """Best-effort int coercion; falls back to ``default`` for non-ints.

    Tool parameters declared with ``ToolParam(...)`` as the default are only
    replaced when the caller (LLM) supplies a real value. When a tool is
    invoked without the argument, we may receive the ``ToolParam`` sentinel,
    so we coerce defensively.
    """
    try:
        return max(1, int(value))
    except (TypeError, ValueError):
        return max(1, default)


def _ensure_clients() -> dict[str, Any] | None:
    """Return clients dict, or None if redis-py is not installed."""
    if not _redis_available():
        return None
    return _get_clients()


def _pool_stats(pool: Any) -> dict[str, Any]:
    """Best-effort extraction of ConnectionPool statistics.

    redis-py's pool attributes vary by version (``ConnectionPool`` vs the newer
    ``BlockingConnectionPool``), so we read defensively.
    """
    stats: dict[str, Any] = {"pool_type": type(pool).__name__}

    # Number of connections created over the lifetime of the pool.
    created = getattr(pool, "_created_connections", None)
    if created is not None:
        stats["created_connections"] = created

    # Connections currently checked out / in use.
    in_use = getattr(pool, "_in_use_connections", None)
    if in_use is None:
        in_use = getattr(pool, "in_use_connections", None)
    if in_use is None:
        in_use = getattr(pool, "num_connections_in_use", None)
    if in_use is not None:
        stats["in_use"] = len(in_use) if not isinstance(in_use, int) else in_use

    # Available (idle) connections.
    available = getattr(pool, "_available_connections", None)
    if available is None:
        available = getattr(pool, "available_connections", None)
    if available is not None:
        stats["available"] = len(available) if not isinstance(available, int) else available

    # Max connections configured for the pool.
    max_conn = getattr(pool, "max_connections", None)
    if max_conn is not None:
        stats["max_connections"] = max_conn

    return stats


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_redis_pool_stats",
    "Get redis-py ConnectionPool stats (created, in-use, available, max) for each registered client",
)
def get_redis_pool_stats() -> dict:
    clients = _ensure_clients()
    if clients is None:
        return {"error": "redis-py is not installed"}

    if not clients:
        return {
            "message": "No Redis clients registered. Call register_redis_client(name, client) to register one.",
            "registered_count": 0,
        }

    result = []
    for name, client in clients.items():
        pool = getattr(client, "connection_pool", None)
        if pool is None:
            result.append({"name": name, "error": "Client has no connection_pool attribute"})
            continue
        result.append({"name": name, **_pool_stats(pool)})

    return {"registered_count": len(clients), "clients": result}


@debug_tool(
    "get_redis_info",
    "Execute INFO on each registered Redis client and parse key sections (clients, memory, dbSize, uptime)",
)
def get_redis_info() -> dict:
    clients = _ensure_clients()
    if clients is None:
        return {"error": "redis-py is not installed"}

    if not clients:
        return {
            "message": "No Redis clients registered. Call register_redis_client(name, client) to register one.",
            "registered_count": 0,
        }

    # Key sections / fields we surface from the full INFO output.
    interest = {
        "Server": ["redis_version", "uptime_in_seconds", "uptime_in_days"],
        "Clients": ["connected_clients", "blocked_clients"],
        "Memory": ["used_memory_human", "used_memory_peak_human", "maxmemory_human"],
        "Stats": ["total_connections_received", "total_commands_processed"],
        "Keyspace": None,  # all keys (db0, db1, ...)
    }

    result = []
    for name, client in clients.items():
        try:
            info = client.info()
        except Exception as exc:  # network / auth errors
            result.append({"name": name, "error": f"Failed to execute INFO: {exc}"})
            continue

        parsed: dict[str, Any] = {}
        for section, fields in interest.items():
            if section == "Keyspace":
                keyspace = {k: v for k, v in info.items() if k.startswith("db")}
                parsed["keyspace"] = keyspace
                continue
            if fields is None:
                parsed[section] = {k: v for k, v in info.items()}
                continue
            parsed[section] = {k: info.get(k) for k in fields if k in info}

        # Convenience roll-ups requested by the task.
        parsed["connected_clients"] = info.get("connected_clients")
        parsed["used_memory_human"] = info.get("used_memory_human")
        parsed["db_size"] = info.get("dbsize") or _compute_dbsize(info)
        parsed["uptime_in_seconds"] = info.get("uptime_in_seconds")

        result.append({"name": name, "info": parsed})

    return {"registered_count": len(clients), "clients": result}


def _compute_dbsize(info: dict) -> int:
    """Sum up keys across all keyspace DBs reported by INFO."""
    total = 0
    for k, v in info.items():
        if k.startswith("db") and isinstance(v, dict):
            total += int(v.get("keys", 0))
    return total


@debug_tool(
    "get_redis_latency",
    "Measure Redis PING latency over 10 samples (min/avg/max in ms) for each registered client",
)
def get_redis_latency(
    samples: int = ToolParam("Number of PING samples to take (default 10)", required=False),
) -> dict:
    clients = _ensure_clients()
    if clients is None:
        return {"error": "redis-py is not installed"}

    if not clients:
        return {
            "message": "No Redis clients registered. Call register_redis_client(name, client) to register one.",
            "registered_count": 0,
        }

    n = _coerce_int(samples, default=10)
    result = []
    for name, client in clients.items():
        latencies: list[float] = []
        errors = 0
        for _ in range(n):
            start = time.perf_counter()
            try:
                client.ping()
                latencies.append((time.perf_counter() - start) * 1000.0)
            except Exception:
                errors += 1

        if latencies:
            entry = {
                "name": name,
                "samples": len(latencies),
                "errors": errors,
                "min_ms": round(min(latencies), 3),
                "avg_ms": round(sum(latencies) / len(latencies), 3),
                "max_ms": round(max(latencies), 3),
            }
        else:
            entry = {"name": name, "samples": 0, "errors": errors, "error": "All PING attempts failed"}
        result.append(entry)

    return {"registered_count": len(clients), "clients": result}


@debug_tool(
    "get_redis_config",
    "Get CONFIG GET for key Redis settings (maxmemory, maxmemory-policy, timeout) per registered client",
)
def get_redis_config() -> dict:
    clients = _ensure_clients()
    if clients is None:
        return {"error": "redis-py is not installed"}

    if not clients:
        return {
            "message": "No Redis clients registered. Call register_redis_client(name, client) to register one.",
            "registered_count": 0,
        }

    settings_of_interest = [
        "maxmemory",
        "maxmemory-policy",
        "timeout",
        "maxclients",
        "appendonly",
        "save",
        "bind",
        "databases",
    ]

    result = []
    for name, client in clients.items():
        try:
            raw = client.config_get()
        except Exception as exc:  # CONFIG may be disabled via rename-command / ACLs
            result.append({"name": name, "error": f"Failed to execute CONFIG GET: {exc}"})
            continue

        # CONFIG GET returns a flat dict of {key: value}; pick out what we want
        # and also keep the full map for completeness.
        selected = {k: raw.get(k) for k in settings_of_interest if k in raw}
        result.append({
            "name": name,
            "settings": selected,
            "raw_count": len(raw),
        })

    return {"registered_count": len(clients), "clients": result}
