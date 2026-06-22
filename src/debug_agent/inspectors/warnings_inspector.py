"""Warnings inspector: capture and list runtime warnings via a custom showwarning hook."""

from __future__ import annotations

import builtins
import threading
import warnings
from collections import deque
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Capture buffer ──────────────────────────────────────────────────────────

_warnings_lock = threading.Lock()
_warning_buffer: deque = deque(maxlen=200)

# Save the original hook so we can chain to it (e.g. print to stderr).\n_orig_showwarning = warnings.showwarning


def _capture_showwarning(message, category, filename, lineno, file=None, line=None):
    """Custom showwarning hook that records warnings into the ring buffer."""
    entry = {
        "message": str(message),
        "category": getattr(category, "__name__", str(category)),
        "filename": filename,
        "line": lineno,
        "source_line": line,
    }
    with _warnings_lock:
        _warning_buffer.append(entry)

    # Chain to the original behaviour so warnings still appear on stderr.
    try:
        _orig_showwarning(message, category, filename, lineno, file, line)
    except Exception:
        pass


# Install our hook.
warnings.showwarning = _capture_showwarning


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_warnings",
    "List captured runtime warnings (message, category, filename, line) and active warning filters",
)
def get_warnings(
    limit: int = ToolParam("Max number of recent warnings to return", required=False),
) -> dict:
    with _warnings_lock:
        entries = list(_warning_buffer)

    total = len(entries)
    if limit:
        entries = entries[-limit:]
    # Most recent first
    entries = list(reversed(entries))

    # Also report the active warning filters
    filters = []
    for f in warnings.filters:
        action, msg, cat, mod, lineno = f
        filters.append(
            {
                "action": action,
                "message": str(msg) if msg else "",
                "category": getattr(cat, "__name__", str(cat)) if cat else "",
                "module": str(mod) if mod else "",
                "lineno": lineno if lineno else 0,
            }
        )

    return {
        "total_captured": total,
        "returned": len(entries),
        "buffer_capacity": _warning_buffer.maxlen,
        "warnings": entries,
        "active_filters": filters,
        "filter_count": len(filters),
    }
