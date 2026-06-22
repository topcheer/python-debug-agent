"""Outbound HTTP inspector: connection pool stats and call tracking.

Call ``install_outbound_tracker()`` at application startup to monkey-patch
``requests.Session.request`` and ``httpx.Client.request`` so that outbound
calls are recorded in the in-memory stats buffer.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any
from urllib.parse import urlparse

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Tracking state ──────────────────────────────────────────────────────────

_stats_lock = threading.Lock()
_outbound_stats: dict[str, Any] = {
    "total": 0,
    "latencies": deque(maxlen=1000),
    "errors": 0,
    "hosts": {},
}

_patched = {"requests": False, "httpx": False}


def reset_outbound_stats() -> None:
    """Reset all accumulated outbound HTTP stats (useful for tests)."""
    with _stats_lock:
        _outbound_stats["total"] = 0
        _outbound_stats["latencies"].clear()
        _outbound_stats["errors"] = 0
        _outbound_stats["hosts"] = {}


def _record_call(url: str, duration_ms: float, error: bool = False) -> None:
    """Record a single outbound HTTP call."""
    host = urlparse(url).netloc or "unknown"
    with _stats_lock:
        _outbound_stats["total"] += 1
        _outbound_stats["latencies"].append(duration_ms)
        if error:
            _outbound_stats["errors"] += 1
        _outbound_stats["hosts"][host] = _outbound_stats["hosts"].get(host, 0) + 1


# ─── Monkey-patching ─────────────────────────────────────────────────────────


def install_outbound_tracker() -> dict[str, Any]:
    """Monkey-patch requests.Session.request and httpx.Client.request.

    Returns a summary of what was patched.  Idempotent — calling twice is safe.
    """
    patched = []

    # ── requests ──────────────────────────────────────────────────────────
    try:
        import requests

        if not _patched["requests"]:
            _orig_request = requests.Session.request

            def _patched_request(self, method, url, *args, **kwargs):
                start = time.perf_counter()
                try:
                    resp = _orig_request(self, method, url, *args, **kwargs)
                    elapsed = (time.perf_counter() - start) * 1000
                    _record_call(url, elapsed, error=resp.status_code >= 500)
                    return resp
                except Exception:
                    elapsed = (time.perf_counter() - start) * 1000
                    _record_call(url, elapsed, error=True)
                    raise

            requests.Session.request = _patched_request
            _patched["requests"] = True
            patched.append("requests.Session.request")
    except ImportError:
        pass

    # ── httpx ─────────────────────────────────────────────────────────────
    try:
        import httpx

        if not _patched["httpx"]:
            _orig_httpx_request = httpx.Client.request

            def _patched_httpx_request(self, method, url, *args, **kwargs):
                start = time.perf_counter()
                try:
                    resp = _orig_httpx_request(self, method, url, *args, **kwargs)
                    elapsed = (time.perf_counter() - start) * 1000
                    _record_call(url, elapsed, error=resp.status_code >= 500)
                    return resp
                except Exception:
                    elapsed = (time.perf_counter() - start) * 1000
                    _record_call(url, elapsed, error=True)
                    raise

            httpx.Client.request = _patched_httpx_request
            _patched["httpx"] = True
            patched.append("httpx.Client.request")
    except ImportError:
        pass

    return {
        "patched": patched,
        "already_patched": [k for k, v in _patched.items() if v and k not in patched],
    }


# ─── Tools ───────────────────────────────────────────────────────────────────


def _get_pool_manager_sessions() -> list[tuple[str, Any]]:
    """Discover live connection pool objects from imported HTTP libraries."""
    sessions: list[tuple[str, Any]] = []

    try:
        import requests

        # No global registry of Sessions; we report the class-level defaults.
        sessions.append(("requests.Session (adapters)", requests.Session))
    except ImportError:
        pass

    try:
        import httpx

        sessions.append(("httpx.Client", httpx.Client))
    except ImportError:
        pass

    return sessions


def _inspect_requests_adapter() -> dict[str, Any] | None:
    try:
        import requests
        from requests.adapters import HTTPAdapter

        # Build a throwaway session to read default adapter config.
        s = requests.Session()
        adapter = s.get_adapter("https://example.com")
        pool = getattr(adapter, "_pool_connections", None)
        return {
            "library": "requests",
            "pool_connections": getattr(adapter, "_pool_connections", None),
            "pool_maxsize": getattr(adapter, "_pool_maxsize", None),
            "pool_block": getattr(adapter, "_pool_block", None),
            "proxy_manager_count": len(getattr(adapter, "proxy_manager", {})),
        }
    except Exception:
        return None


def _inspect_httpx_limits() -> dict[str, Any] | None:
    try:
        import httpx

        limits = httpx.Limits()
        return {
            "library": "httpx",
            "max_connections": limits.max_connections,
            "max_keepalive_connections": limits.max_keepalive_connections,
            "keepalive_expiry": limits.keepalive_expiry,
        }
    except Exception:
        return None


@debug_tool(
    "get_http_pool_stats",
    "Connection pool stats for requests.Session, httpx.Client, urllib3.PoolManager",
)
def get_http_pool_stats() -> dict:
    pools: list[dict[str, Any]] = []

    info = _inspect_requests_adapter()
    if info:
        pools.append(info)

    info = _inspect_httpx_limits()
    if info:
        pools.append(info)

    if not pools:
        return {
            "message": "No supported HTTP client library (requests/httpx/urllib3) is installed",
        }

    return {"pool_count": len(pools), "pools": pools}


@debug_tool(
    "get_outbound_summary",
    "Summary of tracked outbound HTTP calls: total, avg latency, error rate, top hosts",
)
def get_outbound_summary() -> dict:
    with _stats_lock:
        total = _outbound_stats["total"]
        errors = _outbound_stats["errors"]
        latencies = list(_outbound_stats["latencies"])
        hosts = dict(_outbound_stats["hosts"])

    if total == 0:
        return {
            "message": "No outbound calls tracked yet. Call install_outbound_tracker() to start.",
            "total": 0,
        }

    avg_latency = sum(latencies) / len(latencies) if latencies else 0

    # Sort hosts by call count descending
    top_hosts = dict(sorted(hosts.items(), key=lambda x: -x[1])[:10])

    return {
        "total": total,
        "tracked_latency_samples": len(latencies),
        "avg_latency_ms": round(avg_latency, 2),
        "error_count": errors,
        "error_rate": f"{errors / total * 100:.1f}%" if total else "0%",
        "top_hosts": top_hosts,
    }
