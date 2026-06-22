"""Metrics inspector: enumerate prometheus_client registered metrics."""

from __future__ import annotations

from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _prometheus_available() -> bool:
    try:
        import prometheus_client  # noqa: F401
        return True
    except ImportError:
        return False


def _collect_metrics() -> list[Any]:
    """Return all metric families from the default REGISTRY."""
    from prometheus_client import REGISTRY

    return list(REGISTRY.collect())


def _family_to_dict(family: Any) -> dict[str, Any]:
    """Convert a prometheus Metric family into a serialisable dict."""
    samples = []
    for s in family.samples:
        samples.append(
            {
                "name": s.name,
                "labels": dict(s.labels) if s.labels else {},
                "value": s.value,
            }
        )
    return {
        "name": family.name,
        "type": str(family.type),
        "documentation": family.documentation,
        "unit": getattr(family, "unit", None),
        "sample_count": len(samples),
        "samples": samples,
    }


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_registered_metrics",
    "List registered prometheus_client metrics (name, type, documentation, samples)",
)
def get_registered_metrics() -> dict:
    if not _prometheus_available():
        return {"error": "prometheus_client is not installed"}

    try:
        families = _collect_metrics()
    except Exception as exc:
        return {"error": f"Failed to collect metrics: {exc}"}

    metrics = []
    for family in families:
        try:
            metrics.append(_family_to_dict(family))
        except Exception:
            continue

    return {
        "total_families": len(metrics),
        "metrics": metrics,
    }


@debug_tool(
    "get_metric_value",
    "Get value(s) for a specific prometheus metric by name",
)
def get_metric_value(
    name: str = ToolParam("Metric name to look up"),
) -> dict:
    if not _prometheus_available():
        return {"error": "prometheus_client is not installed"}

    try:
        families = _collect_metrics()
    except Exception as exc:
        return {"error": f"Failed to collect metrics: {exc}"}

    for family in families:
        if family.name == name:
            d = _family_to_dict(family)
            return {"found": True, "metric": d}

    return {
        "found": False,
        "error": f"No metric family found with name '{name}'",
        "available": [f.name for f in families],
    }
