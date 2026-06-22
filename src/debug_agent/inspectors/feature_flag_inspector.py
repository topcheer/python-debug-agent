"""Feature flag inspector: list and evaluate feature flags.

Register flags at runtime:

    from debug_agent.inspectors.feature_flag_inspector import register_feature_flag
    register_feature_flag("new_ui", enabled=True)
    register_feature_flag("experimental_cache", enabled=False)
    register_feature_flag("ai_search", enabled=True, variant="v2")
"""

from __future__ import annotations

from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ──────────────────────────────────────────────────────────────

_feature_flags: dict[str, dict[str, Any]] = {}


def register_feature_flag(
    name: str,
    enabled: bool,
    variant: str | None = None,
    evaluator: Any = None,
) -> None:
    """Register a feature flag.

    *evaluator* is an optional callable ``(user_context: dict) -> bool`` that
    overrides the static *enabled* value for context-aware evaluation.
    """
    _feature_flags[name] = {
        "enabled": enabled,
        "variant": variant,
        "evaluator": evaluator,
    }


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_feature_flags",
    "List all registered feature flags (name, enabled, variant)",
)
def get_feature_flags() -> dict:
    if not _feature_flags:
        return {
            "count": 0,
            "flags": [],
            "message": (
                "No feature flags registered. "
                "Use register_feature_flag(name, enabled, variant=None)."
            ),
        }

    flags = [
        {
            "name": name,
            "enabled": info["enabled"],
            "variant": info.get("variant"),
        }
        for name, info in _feature_flags.items()
    ]

    enabled_count = sum(1 for f in flags if f["enabled"])

    return {
        "count": len(flags),
        "enabled_count": enabled_count,
        "disabled_count": len(flags) - enabled_count,
        "flags": flags,
    }


@debug_tool(
    "evaluate_flag",
    "Evaluate a feature flag for a specific user context",
)
def evaluate_flag(
    flag_name: str = ToolParam("Name of the feature flag to evaluate"),
    user_context: dict | None = None,
) -> dict:
    flag = _feature_flags.get(flag_name)
    if flag is None:
        return {
            "flag_name": flag_name,
            "found": False,
            "error": f"No feature flag registered with name '{flag_name}'",
            "available": list(_feature_flags.keys()),
        }

    ctx = user_context or {}
    evaluator = flag.get("evaluator")

    if evaluator is not None:
        try:
            result = bool(evaluator(ctx))
        except Exception as exc:
            return {
                "flag_name": flag_name,
                "found": True,
                "error": f"Evaluator raised: {exc}",
                "static_enabled": flag["enabled"],
            }
        return {
            "flag_name": flag_name,
            "found": True,
            "enabled": result,
            "variant": flag.get("variant"),
            "evaluated_with_context": True,
            "context_keys": list(ctx.keys()),
        }

    return {
        "flag_name": flag_name,
        "found": True,
        "enabled": flag["enabled"],
        "variant": flag.get("variant"),
        "evaluated_with_context": False,
        "note": "No context evaluator registered; returning static value.",
    }
