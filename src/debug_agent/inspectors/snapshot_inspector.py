"""Snapshot & diff inspector: collect cross-inspector metrics for point-in-time snapshots."""

from __future__ import annotations

import gc
import os
import threading
import time
import tracemalloc
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Module-level state ───────────────────────────────────────────────────────

_snapshots: dict[int, dict[str, Any]] = {}
_next_id: int = 1


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _get_rss_mb() -> float | None:
    """Return RSS in MB via resource module or psutil."""
    try:
        import resource
        rss_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # On Linux ru_maxrss is in KB; on macOS it is in bytes
        if sys_platform() == "darwin":
            return round(rss_kb / 1024 / 1024, 2)
        return round(rss_kb / 1024, 2)
    except Exception:
        pass

    try:
        import psutil
        proc = psutil.Process(os.getpid())
        return round(proc.memory_info().rss / 1024 / 1024, 2)
    except Exception:
        return None


def sys_platform() -> str:
    import sys
    return sys.platform


def _ensure_tracemalloc() -> tuple[int, int] | None:
    """Ensure tracemalloc is running; return (current, peak) in bytes."""
    if not tracemalloc.is_tracing():
        try:
            tracemalloc.start(10)
        except RuntimeError:
            return None
    try:
        return tracemalloc.get_traced_memory()
    except Exception:
        return None


def _collect_metrics() -> dict[str, Any]:
    """Gather metrics from all available sources."""
    metrics: dict[str, Any] = {}

    # Thread metrics
    metrics["thread_count"] = threading.active_count()

    # Memory: RSS
    rss = _get_rss_mb()
    if rss is not None:
        metrics["memory_rss_mb"] = rss

    # GC stats
    gc_stats = gc.get_stats()
    metrics["gc_collections"] = {f"gen{i}": gc_stats[i]["collections"] for i in range(len(gc_stats))}
    metrics["gc_collected"] = {f"gen{i}": gc_stats[i]["collected"] for i in range(len(gc_stats))}
    metrics["gc_counts"] = {f"gen{i}": gc.get_count()[i] for i in range(len(gc.get_count()))}

    # Tracemalloc
    traced = _ensure_tracemalloc()
    if traced:
        metrics["tracemalloc_current_mb"] = round(traced[0] / 1024 / 1024, 2)
        metrics["tracemalloc_peak_mb"] = round(traced[1] / 1024 / 1024, 2)

    # Database connections (best-effort)
    metrics["active_db_connections"] = _get_db_connections()

    # Cache hit rate (best-effort)
    metrics["cache_hit_rate"] = _get_cache_hit_rate()

    # HTTP request count (best-effort)
    metrics["http_request_count"] = _get_http_request_count()

    # Error count (best-effort)
    metrics["error_count"] = _get_error_count()

    return metrics


def _get_db_connections() -> int | None:
    """Best-effort: get active DB connection count from SQLAlchemy engines."""
    try:
        from sqlalchemy.pool import QueuePool
        total = 0
        for name, mod in list(__import__("sys").modules.items()):
            if "engine" in name.lower() and hasattr(mod, "pool"):
                pool = getattr(mod, "pool", None)
                if isinstance(pool, QueuePool):
                    total += pool.checkedout()
        return total if total > 0 else None
    except Exception:
        return None


def _get_cache_hit_rate() -> float | None:
    """Best-effort: get cache hit rate from Flask-Caching or django.core.cache."""
    try:
        import sys
        for name, mod in list(sys.modules.items()):
            if "flask_caching" in name and hasattr(mod, "cache"):
                cache = getattr(mod, "cache", None)
                if cache and hasattr(cache, "get") and hasattr(cache, "_cache"):
                    # Flask-Caching doesn't expose hit rate directly; skip
                    pass
        return None
    except Exception:
        return None


def _get_http_request_count() -> int | None:
    """Best-effort: get total HTTP requests from the http_tracker inspector."""
    try:
        import sys
        tracker_mod = sys.modules.get("debug_agent.inspectors.http_tracker")
        if tracker_mod is not None:
            buffer = getattr(tracker_mod, "_request_buffer", None)
            if buffer is not None:
                return len(buffer)
    except Exception:
        pass
    return None


def _get_error_count() -> int | None:
    """Best-effort: get error count from the error_tracking inspector."""
    try:
        import sys
        err_mod = sys.modules.get("debug_agent.inspectors.error_tracking")
        if err_mod is not None:
            buffer = getattr(err_mod, "_error_buffer", None)
            if buffer is not None:
                return len(buffer)
    except Exception:
        pass
    return None


def _compute_diff(
    snap1: dict[str, Any], snap2: dict[str, Any]
) -> list[dict[str, Any]]:
    """Compute differences between two snapshot metric dicts."""
    all_keys = sorted(set(snap1.keys()) | set(snap2.keys()))
    changes = []

    for key in all_keys:
        v1 = snap1.get(key)
        v2 = snap2.get(key)

        # Skip nested dicts (gc_collections etc.) for top-level diff, compute for scalars
        if isinstance(v1, dict) or isinstance(v2, dict):
            continue

        if v1 is None and v2 is None:
            continue

        if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
            delta = v2 - v1
            pct = round((delta / v1) * 100, 2) if v1 != 0 else None
            changes.append({
                "metric": key,
                "value1": v1,
                "value2": v2,
                "delta": round(delta, 4),
                "percentage": pct,
            })
        elif v1 != v2:
            changes.append({
                "metric": key,
                "value1": v1,
                "value2": v2,
                "delta": None,
                "percentage": None,
            })

    return changes


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "take_snapshot",
    "Collect metrics across all inspectors (threads, memory, GC, DB, cache, HTTP, errors) into a snapshot",
)
def take_snapshot() -> dict:
    global _next_id

    metrics = _collect_metrics()
    snap_id = _next_id
    _next_id += 1

    _snapshots[snap_id] = {
        "id": snap_id,
        "timestamp": time.time(),
        "metrics": metrics,
    }

    return {
        "snapshot_id": snap_id,
        "total_snapshots": len(_snapshots),
        "metrics": metrics,
    }


@debug_tool(
    "compare_snapshots",
    "Compare two snapshots and return all changed metrics with delta and percentage",
    {
        "snapshot1_id": ToolParam("First (older) snapshot ID"),
        "snapshot2_id": ToolParam("Second (newer) snapshot ID"),
    },
)
def compare_snapshots(
    snapshot1_id: int = ToolParam("First (older) snapshot ID"),
    snapshot2_id: int = ToolParam("Second (newer) snapshot ID"),
) -> dict:
    entry1 = _snapshots.get(snapshot1_id)
    entry2 = _snapshots.get(snapshot2_id)

    if entry1 is None:
        return {"error": f"Snapshot {snapshot1_id} not found. Available: {list(_snapshots.keys())}"}
    if entry2 is None:
        return {"error": f"Snapshot {snapshot2_id} not found. Available: {list(_snapshots.keys())}"}

    m1: dict[str, Any] = entry1["metrics"]
    m2: dict[str, Any] = entry2["metrics"]

    changes = _compute_diff(m1, m2)

    # Also diff nested GC dicts
    gc_diffs = []
    for gc_key in ("gc_collections", "gc_collected", "gc_counts"):
        gc1 = m1.get(gc_key, {})
        gc2 = m2.get(gc_key, {})
        for gen in sorted(set(gc1.keys()) | set(gc2.keys())):
            v1 = gc1.get(gen)
            v2 = gc2.get(gen)
            if isinstance(v1, (int, float)) and isinstance(v2, (int, float)) and v1 != v2:
                delta = v2 - v1
                pct = round((delta / v1) * 100, 2) if v1 != 0 else None
                gc_diffs.append({
                    "metric": f"{gc_key}.{gen}",
                    "value1": v1,
                    "value2": v2,
                    "delta": delta,
                    "percentage": pct,
                })

    return {
        "snapshot1_id": snapshot1_id,
        "snapshot2_id": snapshot2_id,
        "time_delta_seconds": round(entry2["timestamp"] - entry1["timestamp"], 2),
        "changes": changes,
        "gc_changes": gc_diffs,
        "total_metrics_compared": len(changes) + len(gc_diffs),
    }


@debug_tool(
    "list_snapshots",
    "List all stored metric snapshots with their IDs and timestamps",
)
def list_snapshots() -> dict:
    snapshots = []
    for sid in sorted(_snapshots.keys()):
        entry = _snapshots[sid]
        snapshots.append({
            "id": sid,
            "timestamp": entry["timestamp"],
            "metric_keys": list(entry["metrics"].keys()),
        })

    return {
        "total_snapshots": len(snapshots),
        "snapshots": snapshots,
    }
