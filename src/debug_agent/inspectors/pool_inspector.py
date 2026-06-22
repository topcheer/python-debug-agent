"""Pool inspector: deep-dive into database connection pools.

Register pools at runtime for introspection:

    from debug_agent.inspectors.pool_inspector import register_pool
    register_pool("default", engine.pool)

Also auto-detects SQLAlchemy engine pools via ``engine.pool``.
"""

from __future__ import annotations

import time
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ──────────────────────────────────────────────────────────────

_registered_pools: dict[str, Any] = {}

# Per-pool metadata for wait-time and checkout tracking.
#   pool id() -> { checkouts: [(conn_id, thread, ts), ...], wait_times: [ms, ...] }
_pool_meta: dict[int, dict[str, Any]] = {}


def register_pool(name: str, pool: Any) -> None:
    """Register a connection pool (SQLAlchemy pool or custom) under *name*."""
    _registered_pools[name] = pool
    key = id(pool)
    if key not in _pool_meta:
        _pool_meta[key] = {
            "checkouts": [],  # list of {conn_id, thread, ts}
            "wait_times": [],  # list of floats (ms)
        }


def record_pool_checkout(pool: Any, conn_id: Any = None) -> None:
    """Record a connection checkout from *pool* (call from instrumented code)."""
    meta = _pool_meta.get(id(pool))
    if meta is None:
        return
    import threading
    meta["checkouts"].append({
        "conn_id": str(conn_id) if conn_id is not None else None,
        "thread": threading.current_thread().name,
        "ts": time.time(),
    })
    # Cap history
    if len(meta["checkouts"]) > 500:
        meta["checkouts"] = meta["checkouts"][-500:]


def record_pool_wait(pool: Any, wait_ms: float) -> None:
    """Record a connection-acquire wait time (ms) for *pool*."""
    meta = _pool_meta.get(id(pool))
    if meta is None:
        return
    meta["wait_times"].append(wait_ms)
    if len(meta["wait_times"]) > 500:
        meta["wait_times"] = meta["wait_times"][-500:]


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _detect_sqlalchemy_pools() -> list[tuple[str, Any]]:
    """Find SQLAlchemy engine pools via engine.pool attribute."""
    import sys

    pools: list[tuple[str, Any]] = []
    seen: set[int] = set()

    try:
        from sqlalchemy.engine import Engine  # type: ignore
    except ImportError:
        return pools

    for mod in list(sys.modules.values()):
        if mod is None or mod.__name__.startswith("debug_agent"):
            continue
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            try:
                obj = getattr(mod, attr_name)
                if isinstance(obj, Engine):
                    pool = getattr(obj, "pool", None)
                    if pool is not None and id(pool) not in seen:
                        seen.add(id(pool))
                        pools.append((f"{attr_name}_pool", pool))
            except Exception:
                continue
    return pools


def _pool_stats(pool: Any) -> dict[str, Any]:
    """Extract stats from a pool object (SQLAlchemy QueuePool or custom)."""
    stats: dict[str, Any] = {"type": type(pool).__name__}

    # SQLAlchemy QueuePool / SingletonThreadPool / AssertionPool
    for attr, label in [
        ("size", "pool_size"),
        ("checkedin", "checked_in"),
        ("checkedout", "checked_out"),
        ("overflow", "overflow"),
    ]:
        fn = getattr(pool, attr, None)
        if callable(fn):
            try:
                stats[label] = fn()
            except Exception:
                pass

    try:
        status = pool.status()
        stats["status"] = status
    except Exception:
        pass

    # Generic fallback attributes
    for attr in ("_pool", "_overflow", "_max_overflow", "_timeout"):
        val = getattr(pool, attr, None)
        if val is not None and not callable(val):
            if attr == "_pool":
                try:
                    stats["idle_connections"] = len(val)
                except Exception:
                    pass
            elif attr == "_overflow":
                stats["current_overflow"] = val
            elif attr == "_max_overflow":
                stats["max_overflow"] = val
            elif attr == "_timeout":
                stats["timeout"] = val

    return stats


def _all_pools() -> list[tuple[str, Any]]:
    """Combine registered and auto-detected pools (deduplicated by id)."""
    combined: dict[str, Any] = {}
    seen: set[int] = set()

    for name, pool in _registered_pools.items():
        combined[name] = pool
        seen.add(id(pool))

    for name, pool in _detect_sqlalchemy_pools():
        if id(pool) not in seen:
            combined[name] = pool
            seen.add(id(pool))

    return list(combined.items())


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_pool_details",
    "Get connection pool stats: pool size, checked out, overflow, checked in",
)
def get_pool_details(
    name: str | None = None,
) -> dict:
    if name:
        pool = _registered_pools.get(name)
        if pool is None:
            return {"error": f"No pool registered with name '{name}'"}
        return {"name": name, **_pool_stats(pool)}

    pools = _all_pools()
    if not pools:
        return {
            "pool_count": 0,
            "message": (
                "No connection pools found. Use register_pool(name, pool) or "
                "ensure SQLAlchemy engines are loaded."
            ),
        }

    details = []
    for pool_name, pool in pools:
        try:
            details.append({"name": pool_name, **_pool_stats(pool)})
        except Exception as exc:
            details.append({"name": pool_name, "error": str(exc)})

    return {"pool_count": len(details), "pools": details}


@debug_tool(
    "detect_pool_leaks",
    "Heuristic leak detection: connections checked out for more than 30 seconds",
)
def detect_pool_leaks(
    threshold_seconds: float = 0.0,
) -> dict:
    threshold = threshold_seconds if threshold_seconds and threshold_seconds > 0 else 30.0
    now = time.time()
    leaks: list[dict[str, Any]] = []

    for name, pool in _registered_pools.items():
        meta = _pool_meta.get(id(pool), {})
        checkouts = meta.get("checkouts", [])

        # Also inspect SQLAlchemy internals for checked-out connections
        stats = _pool_stats(pool)
        checked_out = stats.get("checked_out", 0)

        long_held = []
        for co in checkouts:
            held = now - co["ts"]
            if held > threshold:
                long_held.append({
                    "conn_id": co["conn_id"],
                    "thread": co["thread"],
                    "held_seconds": round(held, 1),
                })

        if long_held or checked_out > 0:
            leaks.append({
                "name": name,
                "type": stats.get("type"),
                "checked_out": checked_out,
                "long_held_connections": long_held,
                "long_held_count": len(long_held),
                "leak_suspected": len(long_held) > 0,
            })

    # Also check auto-detected pools with high checked_out counts
    for name, pool in _detect_sqlalchemy_pools():
        if name in [l["name"] for l in leaks]:
            continue
        stats = _pool_stats(pool)
        checked_out = stats.get("checked_out", 0)
        if checked_out > 0:
            leaks.append({
                "name": name,
                "type": stats.get("type"),
                "checked_out": checked_out,
                "long_held_connections": [],
                "long_held_count": 0,
                "leak_suspected": False,
                "note": "High checked-out count; enable instrumentation for time-based leak detection.",
            })

    suspected = sum(1 for l in leaks if l.get("leak_suspected"))

    return {
        "threshold_seconds": threshold,
        "pools_inspected": len(leaks),
        "leaks_suspected": suspected,
        "pools": leaks,
    }


@debug_tool(
    "get_pool_wait_stats",
    "Get connection-acquire wait-time statistics for registered pools",
)
def get_pool_wait_stats(
    name: str | None = None,
) -> dict:
    pools_to_check: list[tuple[str, Any]] = []

    if name:
        pool = _registered_pools.get(name)
        if pool is None:
            return {"error": f"No pool registered with name '{name}'"}
        pools_to_check.append((name, pool))
    else:
        pools_to_check = list(_registered_pools.items())

    if not pools_to_check:
        return {
            "pool_count": 0,
            "message": "No pools registered. Use register_pool(name, pool).",
        }

    results = []
    for pool_name, pool in pools_to_check:
        meta = _pool_meta.get(id(pool), {})
        wait_times = meta.get("wait_times", [])

        if not wait_times:
            results.append({
                "name": pool_name,
                "sample_count": 0,
                "message": (
                    "No wait times recorded. Call record_pool_wait(pool, ms) "
                    "from instrumented acquire paths."
                ),
            })
            continue

        avg = sum(wait_times) / len(wait_times)
        results.append({
            "name": pool_name,
            "sample_count": len(wait_times),
            "avg_wait_ms": round(avg, 2),
            "min_wait_ms": round(min(wait_times), 2),
            "max_wait_ms": round(max(wait_times), 2),
            "last_wait_ms": round(wait_times[-1], 2),
        })

    return {"pool_count": len(results), "pools": results}
