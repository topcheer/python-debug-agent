"""Config inspector: configuration snapshots, env vars, and provenance.

Register config dicts at runtime so they can be introspected:

    from debug_agent.inspectors.config_inspector import register_config
    register_config("flask", {"DEBUG": True, "SQLALCHEMY_DATABASE_URI": "..."})

Sensitive keys (matching password|secret|token|api.?key|private.?key|credential)
are automatically masked as ``"***"``.
"""

from __future__ import annotations

import os
import re
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ──────────────────────────────────────────────────────────────

_registered_configs: dict[str, dict[str, Any]] = {}

# Optional provenance tracking: config name -> { key -> source }
_config_sources: dict[str, dict[str, str]] = {}


def register_config(
    name: str,
    config_dict: dict[str, Any],
    sources: dict[str, str] | None = None,
) -> None:
    """Register a config dict under *name*.

    *sources* optionally maps keys to provenance labels (``"env"``,
    ``"file"``, ``"default"``, ...).
    """
    _registered_configs[name] = dict(config_dict)
    if sources:
        _config_sources[name] = dict(sources)


# ─── Helpers ──────────────────────────────────────────────────────────────────

_SENSITIVE_RE = re.compile(r"password|secret|token|api.?key|private.?key|credential", re.IGNORECASE)


def _is_sensitive(key: str) -> bool:
    return bool(_SENSITIVE_RE.search(str(key)))


def _mask(key: str, value: Any) -> Any:
    if _is_sensitive(key):
        return "***"
    return value


def _mask_config(config: dict[str, Any]) -> dict[str, Any]:
    return {k: _mask(k, v) for k, v in config.items()}


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_config_snapshot",
    "Get all registered config values with sensitive keys masked",
)
def get_config_snapshot() -> dict:
    if not _registered_configs:
        return {
            "count": 0,
            "configs": {},
            "message": "No configs registered. Use register_config(name, config_dict).",
        }

    snapshot: dict[str, Any] = {}
    for name, config in _registered_configs.items():
        snapshot[name] = _mask_config(config)

    # Count how many values were masked for transparency.
    masked_total = 0
    for config in _registered_configs.values():
        for key in config:
            if _is_sensitive(key):
                masked_total += 1

    return {
        "count": len(snapshot),
        "masked_values": masked_total,
        "configs": snapshot,
    }


@debug_tool(
    "get_env_vars",
    "Dump os.environ with optional prefix filter; sensitive values are masked",
)
def get_env_vars(
    prefix: str | None = None,
) -> dict:
    env: dict[str, str] = {}
    masked: list[str] = []

    for key in sorted(os.environ):
        if prefix and not key.startswith(prefix):
            continue
        if _is_sensitive(key):
            env[key] = "***"
            masked.append(key)
        else:
            env[key] = os.environ[key]

    return {
        "prefix": prefix or None,
        "total": len(env),
        "masked_count": len(masked),
        "masked_keys": masked,
        "variables": env,
    }


@debug_tool(
    "get_config_sources",
    "Get config provenance — where each value came from (env, file, default)",
)
def get_config_sources(
    name: str | None = None,
) -> dict:
    if name:
        if name not in _registered_configs:
            return {"error": f"No config registered with name '{name}'"}
        sources = _config_sources.get(name, {})
        result: dict[str, Any] = {}
        for key in _registered_configs[name]:
            result[key] = sources.get(key, "default")
        return {"name": name, "sources": result}

    if not _registered_configs:
        return {
            "count": 0,
            "configs": {},
            "message": "No configs registered.",
        }

    all_sources: dict[str, dict[str, str]] = {}
    for cfg_name, config in _registered_configs.items():
        sources = _config_sources.get(cfg_name, {})
        all_sources[cfg_name] = {
            key: sources.get(key, "default") for key in config
        }

    return {
        "count": len(all_sources),
        "configs": all_sources,
    }
