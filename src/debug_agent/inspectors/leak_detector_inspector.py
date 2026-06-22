"""Memory leak detector: tracemalloc snapshots, comparison, and growth analysis."""

from __future__ import annotations

import time
import tracemalloc
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Module-level state ───────────────────────────────────────────────────────

_snapshots: dict[int, dict[str, Any]] = {}
_next_id: int = 1


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _ensure_tracing() -> None:
    """Start tracemalloc if not already running."""
    if not tracemalloc.is_tracing():
        tracemalloc.start(25)


def _snapshot_summary(snap: tracemalloc.Snapshot) -> dict[str, Any]:
    """Build a summary dict for a tracemalloc snapshot."""
    stats = snap.statistics("lineno")
    total_size = sum(s.size for s in stats)
    total_count = sum(s.count for s in stats)
    top_10 = []
    for stat in stats[:10]:
        frame = stat.traceback[0]
        top_10.append({
            "file": frame.filename,
            "line": frame.lineno,
            "size_kb": round(stat.size / 1024, 2),
            "count": stat.count,
        })
    return {
        "total_allocations": total_count,
        "total_size_kb": round(total_size / 1024, 2),
        "top_by_size": top_10,
    }


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "take_heap_snapshot",
    "Take a tracemalloc heap snapshot and return summary of top allocations",
)
def take_heap_snapshot() -> dict:
    global _next_id
    _ensure_tracing()

    snap = tracemalloc.take_snapshot()
    snap_id = _next_id
    _next_id += 1
    summary = _snapshot_summary(snap)
    _snapshots[snap_id] = {
        "id": snap_id,
        "snapshot": snap,
        "timestamp": time.time(),
        "summary": summary,
    }

    return {
        "snapshot_id": snap_id,
        "total_snapshots": len(_snapshots),
        "summary": summary,
    }


@debug_tool(
    "compare_heap_snapshots",
    "Compare two tracemalloc snapshots and return per-file/line allocation differences",
    {
        "snapshot1_id": ToolParam("First (older) snapshot ID"),
        "snapshot2_id": ToolParam("Second (newer) snapshot ID"),
    },
)
def compare_heap_snapshots(
    snapshot1_id: int = ToolParam("First (older) snapshot ID"),
    snapshot2_id: int = ToolParam("Second (newer) snapshot ID"),
) -> dict:
    entry1 = _snapshots.get(snapshot1_id)
    entry2 = _snapshots.get(snapshot2_id)

    if entry1 is None:
        return {"error": f"Snapshot {snapshot1_id} not found. Available: {list(_snapshots.keys())}"}
    if entry2 is None:
        return {"error": f"Snapshot {snapshot2_id} not found. Available: {list(_snapshots.keys())}"}

    snap1: tracemalloc.Snapshot = entry1["snapshot"]
    snap2: tracemalloc.Snapshot = entry2["snapshot"]

    diffs = snap2.compare_to(snap1, "lineno")

    results = []
    for stat in sorted(diffs, key=lambda s: -abs(s.size_diff)):
        frame = stat.traceback[0]
        growth_pct = round((stat.size_diff / stat.size) * 100, 2) if stat.size != 0 else 0.0
        results.append({
            "file": frame.filename,
            "line": frame.lineno,
            "count_diff": stat.count_diff,
            "size_diff_kb": round(stat.size_diff / 1024, 2),
            "current_size_kb": round(stat.size / 1024, 2),
            "growth_percentage": growth_pct,
        })

    return {
        "snapshot1_id": snapshot1_id,
        "snapshot2_id": snapshot2_id,
        "total_diff_entries": len(results),
        "diffs": results[:50],
    }


@debug_tool(
    "get_leak_candidates",
    "Show files/lines with monotonic memory growth across all stored snapshots",
)
def get_leak_candidates() -> dict:
    if len(_snapshots) < 2:
        return {
            "candidates": [],
            "message": "Need at least 2 snapshots. Call take_heap_snapshot again after some activity.",
        }

    sorted_ids = sorted(_snapshots.keys())

    # Build a timeline of per-file/line sizes across snapshots
    timeline: dict[str, list[int]] = {}
    file_line_info: dict[str, dict[str, Any]] = {}

    for sid in sorted_ids:
        snap: tracemalloc.Snapshot = _snapshots[sid]["snapshot"]
        stats = snap.statistics("lineno")
        for stat in stats:
            frame = stat.traceback[0]
            key = f"{frame.filename}:{frame.lineno}"
            timeline.setdefault(key, []).append(stat.size)
            file_line_info.setdefault(key, {"file": frame.filename, "line": frame.lineno})

    candidates = []
    for key, sizes in timeline.items():
        # Pad with zeros for snapshots where this allocation wasn't present
        if len(sizes) < len(sorted_ids):
            sizes = [0] * (len(sorted_ids) - len(sizes)) + sizes

        # Check for monotonic (non-decreasing) growth
        is_monotonic = all(sizes[i] <= sizes[i + 1] for i in range(len(sizes) - 1))
        total_growth = sizes[-1] - sizes[0]

        if is_monotonic and total_growth > 0:
            info = file_line_info[key]
            candidates.append({
                "file": info["file"],
                "line": info["line"],
                "sizes_across_snapshots_kb": [round(s / 1024, 2) for s in sizes],
                "total_growth_kb": round(total_growth / 1024, 2),
            })

    candidates.sort(key=lambda c: -c["total_growth_kb"])

    return {
        "snapshot_count": len(_snapshots),
        "snapshot_ids": sorted_ids,
        "leak_candidates": candidates[:30],
        "total_candidates": len(candidates),
    }
