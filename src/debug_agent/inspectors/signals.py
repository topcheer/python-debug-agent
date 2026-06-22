"""Signals inspector: registered signal handlers and recursion info."""

from __future__ import annotations

import signal as signal_module
import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# Maps signal numbers to human-readable names.
def _signal_name_map() -> dict[int, str]:
    mapping: dict[int, str] = {}
    for attr in dir(signal_module):
        if attr.startswith("SIG") and not attr.startswith("SIG_"):
            try:
                value = getattr(signal_module, attr)
            except Exception:
                continue
            if isinstance(value, int):
                # Prefer the most specific name (SIGTERM over SIGRTMIN+15 etc.).
                mapping.setdefault(value, attr)
    return mapping


def _describe_handler(handler: Any) -> dict[str, Any]:
    """Render a signal handler in a useful, safe form."""
    if handler == signal_module.SIG_DFL:
        return {"kind": "default", "repr": "SIG_DFL"}
    if handler == signal_module.SIG_IGN:
        return {"kind": "ignored", "repr": "SIG_IGN"}
    if callable(handler):
        return {
            "kind": "callable",
            "module": getattr(handler, "__module__", None),
            "qualname": getattr(handler, "__qualname__", getattr(handler, "__name__", None)),
            "repr": repr(handler),
        }
    return {"kind": "other", "repr": repr(handler)}


@debug_tool(
    "get_signal_handlers",
    "List registered signal handlers (signal number, name, handler)",
)
def get_signal_handlers() -> dict:
    name_map = _signal_name_map()
    handlers: list[dict[str, Any]] = []

    # signal_module.valid_signals() exists on Python 3.8+.
    try:
        sig_numbers = sorted(signal_module.valid_signals())
    except Exception:
        sig_numbers = range(1, 65)

    for sig in sig_numbers:
        if sig in (signal_module.SIGKILL, signal_module.SIGSTOP):
            # These cannot be caught/handled; skip to avoid noise.
            continue
        try:
            handler = signal_module.getsignal(sig)
        except (ValueError, OSError):
            continue
        if handler is None:
            continue
        handlers.append({
            "signal": sig,
            "name": name_map.get(sig, f"SIG{sig}"),
            "handler": _describe_handler(handler),
        })

    return {
        "signal_count": len(handlers),
        "handlers": handlers,
    }


@debug_tool(
    "get_recursion_info",
    "Get the Python recursion limit and the current recursion depth",
)
def get_recursion_info() -> dict:
    limit = sys.getrecursionlimit()

    # Lightweight frame walk from this function's caller to count current depth.
    try:
        frame = sys._getframe(1)
        current_depth = 0
        while frame is not None:
            current_depth += 1
            frame = frame.f_back
    except Exception:
        current_depth = 0

    # Best-effort stack depth for the current OS thread (independent of the
    # caller frame walk above).
    try:
        import threading
        current_frames = sys._current_frames()
        tid = threading.current_thread().ident
        thread_frame = current_frames.get(tid) if tid is not None else None
        thread_depth = 0
        while thread_frame is not None:
            thread_depth += 1
            thread_frame = thread_frame.f_back
    except Exception:
        thread_depth = current_depth

    return {
        "recursion_limit": limit,
        "current_depth": current_depth,
        "headroom": max(0, limit - current_depth),
        "thread_depth": thread_depth,
    }
