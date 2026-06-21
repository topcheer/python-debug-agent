"""HTTP request tracker: in-memory ring buffer for recent requests."""

from __future__ import annotations

import time
import threading
from collections import deque

from debug_agent.tool_registry import debug_tool, ToolParam


# Global ring buffer for request tracking
_buffer_lock = threading.Lock()
_request_buffer: deque = deque(maxlen=500)


def record_request(method: str, path: str, status: int, duration_ms: float, client: str = ""):
    """Record an HTTP request. Call this from your middleware."""
    with _buffer_lock:
        _request_buffer.append({
            "timestamp": time.time(),
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": round(duration_ms, 2),
            "client": client,
        })


def _get_all() -> list[dict]:
    with _buffer_lock:
        return list(_request_buffer)


@debug_tool("get_recent_requests", "Get recent HTTP requests from the in-memory ring buffer")
def get_recent_requests(limit: int = ToolParam("Max results to return", required=False)) -> dict:
    reqs = _get_all()
    if limit:
        reqs = reqs[-limit:]
    return {"total": len(_request_buffer), "requests": list(reversed(reqs))}


@debug_tool("get_slow_requests", "Get slowest HTTP requests sorted by duration")
def get_slow_requests(threshold_ms: float = ToolParam("Minimum duration in ms", required=False)) -> dict:
    reqs = _get_all()
    if threshold_ms:
        reqs = [r for r in reqs if r["duration_ms"] >= threshold_ms]
    reqs.sort(key=lambda x: -x["duration_ms"])
    return {"count": len(reqs), "requests": reqs[:20]}


@debug_tool("get_error_requests", "Get all error requests (4xx/5xx status codes)")
def get_error_requests() -> dict:
    reqs = [r for r in _get_all() if r["status"] >= 400]
    reqs.sort(key=lambda x: -x["duration_ms"])
    return {"count": len(reqs), "requests": reqs}


@debug_tool("get_request_stats", "Get HTTP request statistics: count, P50/P95/P99 latency, error rate")
def get_request_stats() -> dict:
    import math

    reqs = _get_all()
    if not reqs:
        return {"message": "No requests recorded yet"}

    durations = sorted([r["duration_ms"] for r in reqs])
    n = len(durations)

    def percentile(p: float) -> float:
        idx = min(int(math.ceil(p * n)) - 1, n - 1)
        return round(durations[idx], 2)

    errors = sum(1 for r in reqs if r["status"] >= 400)

    # Group by path
    by_path: dict[str, int] = {}
    for r in reqs:
        by_path[r["path"]] = by_path.get(r["path"], 0) + 1

    return {
        "total_requests": n,
        "error_count": errors,
        "error_rate": f"{errors / n * 100:.1f}%",
        "latency_ms": {
            "min": durations[0],
            "p50": percentile(0.5),
            "p95": percentile(0.95),
            "p99": percentile(0.99),
            "max": durations[-1],
        },
        "top_paths": dict(sorted(by_path.items(), key=lambda x: -x[1])[:10]),
    }
