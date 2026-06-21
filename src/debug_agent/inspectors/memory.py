"""Memory profiler inspector: tracemalloc, object counts, GC details, reference cycles."""

from __future__ import annotations

import gc
import tracemalloc
from collections import Counter
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


@debug_tool(
    "get_tracemalloc_stats",
    "Get Python tracemalloc statistics: top allocations by file/line, traced memory",
)
def get_tracemalloc_stats(limit: int = ToolParam("Max number of top allocations to return", required=False)) -> dict:
    if not tracemalloc.is_tracing():
        try:
            tracemalloc.start(10)
        except RuntimeError:
            return {"error": "tracemalloc could not be started"}

    snapshot = tracemalloc.take_snapshot()
    top = snapshot.statistics("lineno")
    current, peak = tracemalloc.get_traced_memory()

    allocations = []
    n = limit if limit and limit > 0 else 20
    for stat in top[:n]:
        frame = stat.traceback[0]
        allocations.append({
            "file": frame.filename,
            "line": frame.lineno,
            "size_kb": round(stat.size / 1024, 2),
            "count": stat.count,
        })

    return {
        "traced_memory_mb": round(current / 1024 / 1024, 2),
        "peak_memory_mb": round(peak / 1024 / 1024, 2),
        "top_allocations": allocations,
        "total_traced_blocks": sum(s.count for s in top),
    }


@debug_tool(
    "get_object_counts",
    "Count live Python objects by type via gc.get_objects() summary",
)
def get_object_counts(limit: int = ToolParam("Max number of type entries to return", required=False)) -> dict:
    all_objects = gc.get_objects()
    type_counter: Counter = Counter()
    for obj in all_objects:
        type_counter[type(obj).__name__] += 1

    n = limit if limit and limit > 0 else 20
    top_types = type_counter.most_common(n)
    return {
        "total_objects": len(all_objects),
        "unique_types": len(type_counter),
        "top_types": {t: c for t, c in top_types},
    }


@debug_tool(
    "get_gc_stats",
    "Get garbage collector statistics: collections, collected, and uncollectable counts per generation",
)
def get_gc_stats() -> dict:
    stats = gc.get_stats()
    threshold = gc.get_threshold()
    return {
        "generations": [
            {
                "generation": i,
                "collections": s["collections"],
                "collected": s["collected"],
                "uncollectable": s["uncollectable"],
            }
            for i, s in enumerate(stats)
        ],
        "thresholds": {"gen0": threshold[0], "gen1": threshold[1], "gen2": threshold[2]},
        "current_counts": {"gen0": gc.get_count()[0], "gen1": gc.get_count()[1], "gen2": gc.get_count()[2]},
        "garbage_list_size": len(gc.garbage),
        "debug_flags": gc.get_debug(),
    }


@debug_tool(
    "get_ref_cycles",
    "Count reference cycles detected by the garbage collector",
)
def get_ref_cycles() -> dict:
    # Save current debug flags
    old_flags = gc.get_debug()
    gc.set_debug(gc.DEBUG_SAVEALL)

    before = len(gc.get_objects())
    collected = gc.collect()
    after = len(gc.get_objects())

    # Analyze what was collected (stored in gc.garbage when DEBUG_SAVEALL)
    cycle_types: Counter = Counter()
    for obj in gc.garbage:
        cycle_types[type(obj).__name__] += 1

    # Restore
    gc.set_debug(old_flags)
    gc.garbage.clear()

    return {
        "objects_collected": collected,
        "objects_freed": before - after,
        "reference_cycle_types": dict(cycle_types.most_common(15)),
        "total_cycles_found": sum(cycle_types.values()),
    }
