"""Async task inspector: pending asyncio tasks and event loop details."""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


def _get_running_loop() -> asyncio.AbstractEventLoop | None:
    """Try to get the currently running event loop."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        # No running loop in this thread
        pass
    try:
        return asyncio.get_event_loop()
    except RuntimeError:
        return None


@debug_tool(
    "get_async_tasks",
    "List pending asyncio tasks if running in async mode",
)
def get_async_tasks() -> dict:
    loop = _get_running_loop()
    if loop is None:
        return {
            "message": "No running asyncio event loop found. The app may be using synchronous mode.",
            "has_running_loop": False,
        }

    try:
        all_tasks = asyncio.all_tasks(loop=loop)
    except RuntimeError:
        return {"error": "Could not enumerate asyncio tasks"}

    tasks_info = []
    for task in all_tasks:
        coro = task.get_coro() if hasattr(task, "get_coro") else None
        tasks_info.append({
            "name": task.get_name() if hasattr(task, "get_name") else str(task),
            "done": task.done(),
            "cancelled": task.cancelled(),
            "coroutine": str(coro) if coro else None,
            "stack_repr": repr(task),
        })

    return {
        "has_running_loop": True,
        "total_tasks": len(all_tasks),
        "pending_tasks": sum(1 for t in all_tasks if not t.done()),
        "done_tasks": sum(1 for t in all_tasks if t.done()),
        "tasks": tasks_info[:50],
    }


@debug_tool(
    "get_event_loop_info",
    "Get asyncio event loop details: type, running state, debug mode",
)
def get_event_loop_info() -> dict:
    loop = _get_running_loop()
    if loop is None:
        return {
            "message": "No running asyncio event loop found",
            "has_running_loop": False,
        }

    info = {
        "has_running_loop": True,
        "loop_type": type(loop).__name__,
        "is_running": loop.is_running(),
        "is_closed": loop.is_closed(),
        "debug_mode": loop.get_debug(),
    }

    # Try to get additional details
    try:
        info["time"] = loop.time()
    except Exception:
        pass

    # Async generator count
    try:
        info["async_generator_count"] = len(loop._asyncgens) if hasattr(loop, "_asyncgens") else 0
    except Exception:
        pass

    # Check for uvloop
    try:
        import uvloop
        info["using_uvloop"] = isinstance(loop, uvloop.Loop)
    except ImportError:
        info["using_uvloop"] = False

    # Task count
    try:
        all_tasks = asyncio.all_tasks(loop=loop)
        info["active_task_count"] = len(all_tasks)
    except RuntimeError:
        info["active_task_count"] = 0

    return info
