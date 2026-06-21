"""Thread inspector: live thread info, counts, and per-thread tracebacks."""

from __future__ import annotations

import sys
import threading
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


@debug_tool(
    "get_thread_info",
    "List all threads with name, daemon status, and alive status",
)
def get_thread_info() -> dict:
    threads = threading.enumerate()
    return {
        "total_threads": len(threads),
        "active_count": threading.active_count(),
        "current_thread": threading.current_thread().name,
        "threads": [
            {
                "name": t.name,
                "ident": t.ident,
                "daemon": t.daemon,
                "alive": t.is_alive(),
                "native_id": getattr(t, "native_id", None),
            }
            for t in threads
        ],
    }


@debug_tool(
    "get_thread_count",
    "Get the number of active threads in the process",
)
def get_thread_count() -> dict:
    return {
        "active_count": threading.active_count(),
        "enumerated_count": len(threading.enumerate()),
        "main_thread_alive": threading.main_thread().is_alive(),
    }


@debug_tool(
    "get_thread_traceback",
    "Get the Python traceback (stack frames) for a specific thread by name or ID",
)
def get_thread_traceback(
    thread_name: str = ToolParam("Thread name to look up (use 'MainThread' for main thread)", required=False),
    thread_id: int = ToolParam("Thread identifier (OS-level TID) to look up", required=False),
) -> dict:
    frames = sys._current_frames()
    thread_map = {t.ident: t for t in threading.enumerate()}

    target_tid = None
    matched_name = None

    if thread_id is not None:
        target_tid = thread_id
        t = thread_map.get(thread_id)
        matched_name = t.name if t else f"tid-{thread_id}"
    elif thread_name:
        for t in threading.enumerate():
            if t.name == thread_name:
                target_tid = t.ident
                matched_name = t.name
                break
        if target_tid is None:
            return {"error": f"No thread found with name '{thread_name}'"}
    else:
        # Default to current thread
        target_tid = threading.current_thread().ident
        matched_name = threading.current_thread().name

    frame = frames.get(target_tid)
    if not frame:
        return {"error": f"No frame found for thread '{matched_name}' (tid={target_tid})"}

    stack = []
    f = frame
    while f:
        stack.append({
            "file": f.f_code.co_filename,
            "line": f.f_lineno,
            "function": f.f_code.co_name,
        })
        f = f.f_back

    return {
        "thread_name": matched_name,
        "thread_id": target_tid,
        "stack_depth": len(stack),
        "frames": stack[:30],
    }
