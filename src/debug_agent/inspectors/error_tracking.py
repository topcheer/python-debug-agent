"""Error tracking inspector: capture and analyse unhandled exceptions.

Installs a global ``sys.excepthook`` and provides helpers to hook into
Flask / WSGI for request-scoped errors.  A ring buffer (max 50) keeps the
most recent exceptions for inspection.
"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback as tb_mod
from collections import Counter, deque
from datetime import datetime, timezone
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Ring buffer & state ──────────────────────────────────────────────────────

_MAX_BUFFER = 50
_error_buffer: deque = deque(maxlen=_MAX_BUFFER)
_buffer_lock = threading.Lock()
_original_excepthook = sys.excepthook
_installed = False


# ─── Capture helpers ──────────────────────────────────────────────────────────


def capture_error(
    exc_type: type,
    value: BaseException,
    tb: Any,
    request_path: str | None = None,
) -> None:
    """Append an exception to the ring buffer."""
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "epoch": time.time(),
        "type": exc_type.__name__ if exc_type else "Unknown",
        "message": str(value),
        "traceback": "".join(tb_mod.format_exception(exc_type, value, tb)),
        "request_path": request_path,
    }
    with _buffer_lock:
        _error_buffer.append(entry)


def _excepthook(exc_type, value, tb):  # noqa: A002  (tb shadows stdlib name)
    """Replacement sys.excepthook that records the exception before delegating."""
    capture_error(exc_type, value, tb)
    _original_excepthook(exc_type, value, tb)


def install_error_hooks() -> None:
    """Install the global ``sys.excepthook`` override (idempotent)."""
    global _installed
    if _installed:
        return
    sys.excepthook = _excepthook
    _installed = True


def install_flask_error_handler(app: Any) -> None:
    """Register a catch-all Flask error handler that records exceptions."""
    try:
        from flask import request, jsonify  # type: ignore
    except ImportError:
        return

    @app.errorhandler(Exception)
    def _capture_flask_error(e):  # noqa: ANN202
        capture_error(
            type(e), e, e.__traceback__,
            request_path=request.path if request else None,
        )
        # Re-raise so existing handlers / Flask defaults still apply
        try:
            return app.handle_exception(e)
        except Exception:
            return jsonify({"error": type(e).__name__, "message": str(e)}), 500


def install_wsgi_middleware(app: Any) -> Any:
    """Wrap a WSGI app so unhandled exceptions are captured."""

    def middleware(environ, start_response):
        try:
            return app(environ, start_response)
        except Exception as exc:
            capture_error(
                type(exc), exc, exc.__traceback__,
                request_path=environ.get("PATH_INFO"),
            )
            raise

    return middleware


# Auto-install the global excepthook on import
install_error_hooks()


# ─── Tools ────────────────────────────────────────────────────────────────────


def _get_all() -> list[dict]:
    with _buffer_lock:
        return list(_error_buffer)


@debug_tool(
    "get_recent_errors",
    "Get recent unhandled exceptions from the in-memory ring buffer (max 50)",
)
def get_recent_errors(
    limit: int = ToolParam("Max results to return", required=False),
) -> dict:
    errors = _get_all()
    if limit:
        errors = errors[-limit:]
    return {
        "total_captured": len(_error_buffer),
        "buffer_max": _MAX_BUFFER,
        "errors": list(reversed(errors)),
    }


@debug_tool(
    "get_error_stats",
    "Get error statistics: total, rate per minute, top error types",
)
def get_error_stats() -> dict:
    errors = _get_all()
    if not errors:
        return {"total": 0, "message": "No errors captured yet"}

    now = time.time()
    oldest = min(e["epoch"] for e in errors)
    elapsed_minutes = max((now - oldest) / 60, 1 / 60)  # avoid div-by-zero

    type_counts = Counter(e["type"] for e in errors)

    return {
        "total": len(errors),
        "buffer_max": _MAX_BUFFER,
        "rate_per_minute": round(len(errors) / elapsed_minutes, 2),
        "time_window_minutes": round(elapsed_minutes, 1),
        "top_error_types": type_counts.most_common(10),
    }


@debug_tool(
    "get_error_patterns",
    "Group similar errors by exception type and message pattern",
)
def get_error_patterns() -> dict:
    errors = _get_all()
    if not errors:
        return {"patterns": [], "message": "No errors captured yet"}

    def _normalise_message(msg: str) -> str:
        """Collapse variable parts of an error message for grouping."""
        import re
        # Replace IDs, numbers, hex, file paths, and quoted strings
        msg = re.sub(r"\b[0-9a-f]{8,}\b", "<hex>", msg, flags=re.IGNORECASE)
        msg = re.sub(r"\b\d+\b", "<N>", msg)
        msg = re.sub(r"/[/^\s]+", "<path>", msg)
        msg = re.sub(r"'[^']*'", "'<str>'", msg)
        msg = re.sub(r'"[^"]*"', '"<str>"', msg)
        return msg[:200]

    groups: dict[str, dict[str, Any]] = {}
    for err in errors:
        pattern_key = f"{err['type']}: {_normalise_message(err['message'])}"
        if pattern_key not in groups:
            groups[pattern_key] = {
                "pattern": pattern_key,
                "count": 0,
                "type": err["type"],
                "example_message": err["message"],
                "first_seen": err["timestamp"],
                "last_seen": err["timestamp"],
                "request_paths": set(),
            }
        g = groups[pattern_key]
        g["count"] += 1
        g["last_seen"] = err["timestamp"]
        if err.get("request_path"):
            g["request_paths"].add(err["request_path"])

    # Sort by count desc and convert sets to lists
    sorted_groups = sorted(groups.values(), key=lambda x: -x["count"])
    for g in sorted_groups:
        g["request_paths"] = sorted(g["request_paths"])

    return {
        "pattern_count": len(sorted_groups),
        "total_errors": len(errors),
        "patterns": sorted_groups,
    }
