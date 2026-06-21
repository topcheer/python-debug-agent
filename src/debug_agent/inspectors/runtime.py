"""Runtime inspector: GC, memory, threads, process info."""

from __future__ import annotations

import gc
import os
import sys
import threading
import time
import tracemalloc
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


@debug_tool("get_gc_stats", "Get garbage collector statistics: collection counts per generation")
def get_gc_stats() -> dict:
    counts = gc.get_count()  # (gen0, gen1, gen2) counts
    return {
        "generation_counts": {"gen0": counts[0], "gen1": counts[1], "gen2": counts[2]},
        "garbage_count": len(gc.garbage),
        "total_objects": len(gc.get_objects()),
    }


@debug_tool("get_memory_summary", "Get process memory usage: RSS, VMS, and Python heap info")
def get_memory_summary() -> dict:
    try:
        import resource
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # macOS reports in bytes, Linux in KB
        if sys.platform == "darwin":
            rss_mb = rss / 1024 / 1024
        else:
            rss_mb = rss / 1024
    except ImportError:
        rss_mb = 0

    import ctypes
    info = {"rss_mb": round(rss_mb, 2)}

    # Python object counts
    counts = {}
    for obj in gc.get_objects():
        t = type(obj).__name__
        counts[t] = counts.get(t, 0) + 1
    top_types = sorted(counts.items(), key=lambda x: -x[1])[:15]
    info["top_object_types"] = {t: c for t, c in top_types}
    info["total_objects"] = sum(counts.values())

    return info


@debug_tool("trigger_gc", "Trigger garbage collection and show before/after comparison")
def trigger_gc() -> dict:
    before = len(gc.get_objects())
    collected = gc.collect()
    after = len(gc.get_objects())
    return {
        "objects_before": before,
        "objects_collected": collected,
        "objects_after": after,
        "freed": before - after,
    }


@debug_tool("get_thread_summary", "Get thread state overview: count, names, daemon status")
def get_thread_summary() -> dict:
    threads = threading.enumerate()
    return {
        "total_threads": len(threads),
        "threads": [
            {"name": t.name, "ident": t.ident, "daemon": t.daemon, "alive": t.is_alive()}
            for t in threads
        ],
    }


@debug_tool("get_thread_dump", "Get stack traces for all threads")
def get_thread_dump() -> dict:
    frames = sys._current_frames()
    result = {}
    for tid, frame in frames.items():
        stack = []
        f = frame
        while f:
            stack.append({"file": f.f_code.co_filename, "line": f.f_lineno, "function": f.f_code.co_name})
            f = f.f_back
        # Find thread name
        tname = "unknown"
        for t in threading.enumerate():
            if t.ident == tid:
                tname = t.name
                break
        result[tname] = stack[:20]
    return result


@debug_tool("get_runtime_info", "Get Python runtime info: version, platform, uptime")
def get_runtime_info() -> dict:
    return {
        "python_version": sys.version,
        "platform": sys.platform,
        "executable": sys.executable,
        "pid": os.getpid(),
        "argv": sys.argv,
        "path_count": len(sys.path),
    }


@debug_tool("get_memory_allocations", "Get top memory allocations using tracemalloc (if enabled)")
def get_memory_allocations() -> dict:
    if not tracemalloc.is_tracing():
        return {"error": "tracemalloc is not enabled. Call tracemalloc.start() to enable."}
    snapshot = tracemalloc.take_snapshot()
    top = snapshot.statistics("lineno")
    return {
        "top_allocations": [
            {"file": str(s.traceback), "size_kb": round(s.size / 1024, 2), "count": s.count}
            for s in top[:20]
        ],
    }


@debug_tool("get_tracemalloc_status", "Check if tracemalloc is enabled and its configuration")
def get_tracemalloc_status() -> dict:
    return {
        "enabled": tracemalloc.is_tracing(),
        "traced_memory_mb": round(sum((c.size for c in tracemalloc.get_traced_memory())) / 1024 / 1024, 2)
        if tracemalloc.is_tracing()
        else 0,
    }
