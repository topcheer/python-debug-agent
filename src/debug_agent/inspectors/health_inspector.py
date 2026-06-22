"""Health inspector: pluggable health checks with UP / DOWN / DEGRADED status.

Register health checks via decorator:

    from debug_agent.inspectors.health_inspector import register_health_check

    @register_health_check("database")
    def check_database():
        # ... run check ...
        return {"status": "UP", "details": {"latency_ms": 2.1}}
"""

from __future__ import annotations

import time
from typing import Any, Callable

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ─────────────────────────────────────────────────────────────

_health_checks: dict[str, Callable[..., Any]] = {}


def register_health_check(name: str):
    """Decorator: register *fn* as a health check under *name*."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        _health_checks[name] = fn
        return fn

    return decorator


# ─── Helpers ──────────────────────────────────────────────────────────────────


_VALID_STATUSES = {"UP", "DOWN", "DEGRADED"}


def _run_check(name: str, fn: Callable[..., Any]) -> dict:
    start = time.time()
    try:
        result = fn()
        elapsed_ms = round((time.time() - start) * 1000, 2)

        if isinstance(result, dict):
            status = str(result.get("status", "UP")).upper()
            if status not in _VALID_STATUSES:
                status = "UP"
            return {
                "name": name,
                "status": status,
                "latency_ms": elapsed_ms,
                "details": result.get("details", {k: v for k, v in result.items() if k != "status"}),
            }

        # Non-dict truthy / falsy results
        if result in _VALID_STATUSES:
            status = result
        elif result:
            status = "UP"
        else:
            status = "DOWN"
        return {"name": name, "status": status, "latency_ms": elapsed_ms}

    except Exception as exc:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "name": name,
            "status": "DOWN",
            "latency_ms": elapsed_ms,
            "error": f"{type(exc).__name__}: {exc}",
        }


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_health_status",
    "Run all registered health checks and return UP/DOWN/DEGRADED per component",
)
def get_health_status() -> dict:
    if not _health_checks:
        return {
            "components": [],
            "overall": "UNKNOWN",
            "message": "No health checks registered. Use @register_health_check(name).",
        }

    results = [_run_check(name, fn) for name, fn in _health_checks.items()]

    statuses = [r["status"] for r in results]
    if all(s == "UP" for s in statuses):
        overall = "UP"
    elif any(s == "DOWN" for s in statuses):
        overall = "DOWN"
    else:
        overall = "DEGRADED"

    return {
        "overall": overall,
        "components_checked": len(results),
        "components": results,
    }


@debug_tool(
    "get_health_detail",
    "Deep-dive into a specific health check component",
)
def get_health_detail(
    component_name: str = ToolParam("Name of the health check component to inspect"),
) -> dict:
    fn = _health_checks.get(component_name)
    if fn is None:
        return {
            "error": f"No health check registered for '{component_name}'",
            "available": list(_health_checks.keys()),
        }

    return _run_check(component_name, fn)
