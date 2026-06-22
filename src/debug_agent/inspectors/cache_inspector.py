"""Cache inspector: stats and management for registered caches.

Register a cache at runtime so the inspector can reach it:

    from debug_agent.inspectors.cache_inspector import register_cache
    register_cache("my_cache", my_cache_obj)

Supports functools.lru_cache, cachetools caches, Django cache backends,
and custom cache objects.
"""

from __future__ import annotations

from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ────────────────────────────────────────────────────────────

_registered_caches: dict[str, Any] = {}


def register_cache(name: str, cache_obj: Any) -> None:
    """Register a cache object under a name so the inspectors can find it."""
    _registered_caches[name] = cache_obj


# ─── Cache type detection ────────────────────────────────────────────────────


def _detect_type(cache_obj: Any) -> str:
    """Return a label describing the cache implementation."""
    # functools.lru_cache / functools.cache wrappers expose cache_info()
    if hasattr(cache_obj, "cache_info") and hasattr(cache_obj, "cache_clear"):
        return "lru_cache"

    # cachetools caches have __contains__ and __len__
    cls_name = type(cache_obj).__module__ + "." + type(cache_obj).__qualname__
    if "cachetools" in type(cache_obj).__module__:
        return "cachetools"

    # Django cache backends expose _cache attribute
    if hasattr(cache_obj, "_cache"):
        return "django"

    # Generic mapping-like caches
    if hasattr(cache_obj, "__contains__") and hasattr(cache_obj, "__len__"):
        return "mapping"

    # Custom caches with stats()/info() methods
    if hasattr(cache_obj, "stats") or hasattr(cache_obj, "info"):
        return "custom"

    return "unknown"


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_cache_info",
    "Get stats for registered caches (lru_cache, cachetools, django, custom)",
)
def get_cache_info(
    name: str = ToolParam("Cache name (omit for all registered caches)", required=False),
) -> dict:
    if name:
        cache_obj = _registered_caches.get(name)
        if cache_obj is None:
            return {"error": f"No cache registered with name '{name}'"}
        return _inspect_cache(name, cache_obj)

    if not _registered_caches:
        return {
            "message": "No caches registered. Call register_cache(name, cache_obj) to register one.",
            "registered_count": 0,
        }

    result = []
    for cache_name, cache_obj in _registered_caches.items():
        try:
            result.append(_inspect_cache(cache_name, cache_obj))
        except Exception as exc:
            result.append({"name": cache_name, "error": str(exc)})

    return {"registered_count": len(result), "caches": result}


def _inspect_cache(name: str, cache_obj: Any) -> dict[str, Any]:
    cache_type = _detect_type(cache_obj)
    info: dict[str, Any] = {"name": name, "type": cache_type}

    # functools.lru_cache
    if cache_type == "lru_cache":
        try:
            ci = cache_obj.cache_info()
            info.update(
                {
                    "hits": getattr(ci, "hits", None),
                    "misses": getattr(ci, "misses", None),
                    "maxsize": getattr(ci, "maxsize", None),
                    "current_size": getattr(ci, "currsize", None),
                }
            )
            return info
        except Exception as exc:
            info["error"] = str(exc)
            return info

    # cachetools / generic mapping
    if cache_type in ("cachetools", "mapping"):
        try:
            info["size"] = len(cache_obj)
        except Exception:
            info["size"] = None
        info["maxsize"] = getattr(cache_obj, "maxsize", None)
        return info

    # django cache
    if cache_type == "django":
        try:
            inner = getattr(cache_obj, "_cache", None)
            if inner is not None and hasattr(inner, "__len__"):
                info["size"] = len(inner)
            else:
                info["size"] = None
        except Exception:
            info["size"] = None
        info["backend"] = type(cache_obj).__name__
        return info

    # custom: try stats(), info(), size
    if cache_type == "custom":
        for method in ("stats", "info"):
            if hasattr(cache_obj, method):
                try:
                    val = getattr(cache_obj, method)()
                    if isinstance(val, dict):
                        info.update(val)
                    else:
                        info[method] = val
                except Exception:
                    pass
        size = getattr(cache_obj, "size", None)
        if size is not None:
            info["size"] = size() if callable(size) else size
        return info

    return info


@debug_tool(
    "get_cache_keys",
    "List keys in a registered cache with optional prefix filter",
)
def get_cache_keys(
    name: str = ToolParam("Cache name"),
    prefix: str = ToolParam("Optional key prefix to filter by", required=False),
) -> dict:
    cache_obj = _registered_caches.get(name)
    if cache_obj is None:
        return {"error": f"No cache registered with name '{name}'"}

    cache_type = _detect_type(cache_obj)
    keys: list[Any] = []

    try:
        if cache_type == "lru_cache":
            return {
                "name": name,
                "type": cache_type,
                "message": "lru_cache does not expose its keys",
            }

        # Django locmem / cachetools / generic mapping
        inner = cache_obj
        if cache_type == "django":
            inner = getattr(cache_obj, "_cache", cache_obj)

        if hasattr(inner, "keys"):
            keys = list(inner.keys())
        elif hasattr(inner, "__iter__"):
            keys = [k for k in inner]
    except Exception as exc:
        return {"error": f"Could not enumerate keys: {exc}"}

    if prefix:
        keys = [k for k in keys if str(k).startswith(prefix)]

    return {
        "name": name,
        "type": cache_type,
        "total": len(keys),
        "keys": keys[:500],  # cap to avoid huge responses
    }


@debug_tool(
    "clear_cache",
    "Clear a registered cache (lru_cache: cache_clear, cachetools/django: clear)",
)
def clear_cache(
    name: str = ToolParam("Cache name"),
) -> dict:
    cache_obj = _registered_caches.get(name)
    if cache_obj is None:
        return {"error": f"No cache registered with name '{name}'"}

    cache_type = _detect_type(cache_obj)

    try:
        if cache_type == "lru_cache":
            cache_obj.cache_clear()
        elif hasattr(cache_obj, "clear"):
            cache_obj.clear()
        else:
            return {
                "error": f"Cache '{name}' (type: {cache_type}) does not support clearing",
            }
    except Exception as exc:
        return {"error": f"Failed to clear cache '{name}': {exc}"}

    return {"name": name, "type": cache_type, "cleared": True}
