"""CPU profiler inspector: cProfile-based profiling with auto-stop and top-function analysis."""

from __future__ import annotations

import cProfile
import io
import pstats
import threading
import time
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Module-level state ───────────────────────────────────────────────────────

_profiler: cProfile.Profile | None = None
_last_stats: pstats.Stats | None = None
_timer: threading.Timer | None = None
_lock = threading.Lock()


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _auto_stop() -> None:
    """Auto-stop callback scheduled by ``threading.Timer``."""
    global _profiler, _last_stats
    with _lock:
        if _profiler is not None:
            try:
                _profiler.disable()
            except Exception:
                pass
            _last_stats = pstats.Stats(_profiler)
            _profiler = None


def _extract_functions(stats: pstats.Stats, limit: int, sort_by: str) -> list[dict[str, Any]]:
    """Extract top-N function entries from pstats as a list of dicts."""
    sort_key_map = {
        "cumulative": pstats.SortKey.CUMULATIVE,
        "self": pstats.SortKey.TIME,
        "calls": pstats.SortKey.CALLS,
    }
    key = sort_key_map.get(sort_by, pstats.SortKey.CUMULATIVE)
    stats.sort_stats(key)

    functions: list[dict[str, Any]] = []
    for func, (cc, nc, tt, ct, callers) in stats.stats.items():  # type: ignore[attr-defined]
        filename, line_no, func_name = func
        functions.append({
            "function": func_name,
            "file": filename,
            "line": line_no,
            "cumulative_time": round(ct, 6),
            "self_time": round(tt, 6),
            "calls": nc,
            "per_call_time": round(ct / nc, 6) if nc else 0,
        })
        if len(functions) >= limit:
            break

    return functions


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "start_cpu_profile",
    "Start CPU profiling with cProfile. Auto-stops after duration_seconds.",
    {"duration_seconds": ToolParam("Auto-stop duration in seconds", required=False)},
)
def start_cpu_profile(
    duration_seconds: int = ToolParam("Auto-stop duration in seconds", required=False),
) -> dict:
    global _profiler, _timer
    with _lock:
        if _profiler is not None:
            return {"error": "Profiling already in progress. Call stop_cpu_profile first."}

        _profiler = cProfile.Profile()
        _profiler.enable()

        duration = duration_seconds if duration_seconds and duration_seconds > 0 else 10
        _timer = threading.Timer(duration, _auto_stop)
        _timer.daemon = True
        _timer.start()

    return {
        "status": "profiling started",
        "duration_seconds": duration,
        "message": f"CPU profiling started, will auto-stop in {duration}s.",
    }


@debug_tool(
    "stop_cpu_profile",
    "Stop active CPU profiling and return top 20 functions sorted by cumulative time",
)
def stop_cpu_profile() -> dict:
    global _profiler, _last_stats, _timer

    with _lock:
        # Cancel pending auto-stop if user stops manually
        if _timer is not None:
            _timer.cancel()
            _timer = None

        if _profiler is None and _last_stats is None:
            return {"error": "No active profiling session. Call start_cpu_profile first."}

        if _profiler is not None:
            try:
                _profiler.disable()
            except Exception:
                pass
            _last_stats = pstats.Stats(_profiler)
            _profiler = None

        if _last_stats is None:
            return {"error": "No profiling data available."}

        top = _extract_functions(_last_stats, 20, "cumulative")
        total_calls = _last_stats.total_calls  # type: ignore[attr-defined]

    return {
        "status": "stopped",
        "total_calls": total_calls,
        "top_functions": top,
    }


@debug_tool(
    "get_top_functions",
    "Return top N functions from the last CPU profile with configurable sort",
    {
        "limit": ToolParam("Max number of functions to return", required=False),
        "sort_by": ToolParam("Sort key: cumulative, self, or calls", required=False),
    },
)
def get_top_functions(
    limit: int = ToolParam("Max number of functions to return", required=False),
    sort_by: str = ToolParam("Sort key: cumulative, self, or calls", required=False),
) -> dict:
    global _last_stats

    if _last_stats is None:
        return {"error": "No profiling data available. Run start_cpu_profile then stop_cpu_profile first."}

    n = limit if limit and limit > 0 else 20
    sb = sort_by if sort_by in ("cumulative", "self", "calls") else "cumulative"

    top = _extract_functions(_last_stats, n, sb)
    return {
        "sort_by": sb,
        "limit": n,
        "functions": top,
    }
