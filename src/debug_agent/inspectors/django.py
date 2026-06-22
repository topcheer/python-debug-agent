"""Django inspector: settings, URLs, models, and cache backends.

All tools degrade gracefully when Django is not installed or not configured.
They introspect the active Django project via the standard ``django`` APIs so
no manual registration is required.
"""

from __future__ import annotations

from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _django_configured() -> bool:
    try:
        import django
        from django.conf import settings
        return bool(settings.configured)
    except Exception:
        return False


def _mask_secret(value: Any) -> Any:
    """Mask values that look like secrets (strings keyed off context in caller)."""
    if isinstance(value, str) and value:
        return "***masked***" if len(value) > 4 else "***"
    if isinstance(value, (list, tuple)):
        return [_mask_secret(v) for v in value]
    if isinstance(value, dict):
        return {k: _mask_secret(v) for k, v in value.items()}
    return value


# Settings key substrings that should be masked in the audit output.
_SECRET_HINTS = ("KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL", "API")


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(hint in upper for hint in _SECRET_HINTS)


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_django_settings",
    "Audit Django settings: INSTALLED_APPS, MIDDLEWARE, DATABASES, and masked secret settings",
)
def get_django_settings() -> dict:
    if not _django_configured():
        return {"error": "Django is not installed or settings are not configured"}

    from django.conf import settings

    # Structured roll-ups requested by the task.
    installed_apps = list(getattr(settings, "INSTALLED_APPS", []) or [])
    middleware = list(getattr(settings, "MIDDLEWARE", []) or [])

    databases = {}
    for name, db in (getattr(settings, "DATABASES", {}) or {}).items():
        entry = dict(db) if isinstance(db, dict) else {}
        # Mask the password inside each database ENGINE/credentials block.
        if "PASSWORD" in entry:
            entry["PASSWORD"] = "***masked***"
        databases[name] = entry

    # Masked secrets: any setting whose key looks like a secret.
    masked: dict[str, Any] = {}
    for key in dir(settings):
        if key.startswith("_"):
            continue
        if not _is_secret_key(key):
            continue
        try:
            masked[key] = _mask_secret(getattr(settings, key))
        except Exception:
            continue

    # A handful of non-sensitive but useful summary settings.
    summary_keys = [
        "DEBUG",
        "SECRET_KEY" if False else "USE_TZ",
        "TIME_ZONE",
        "LANGUAGE_CODE",
        "DEFAULT_CHARSET",
        "ALLOWED_HOSTS",
        "STATIC_URL",
        "MEDIA_URL",
        "ROOT_URLCONF",
        "WSGI_APPLICATION",
        "DEFAULT_AUTO_FIELD",
    ]
    summary: dict[str, Any] = {}
    for key in summary_keys:
        try:
            summary[key] = getattr(settings, key)
        except AttributeError:
            continue

    return {
        "installed_apps": installed_apps,
        "app_count": len(installed_apps),
        "middleware": middleware,
        "middleware_count": len(middleware),
        "databases": databases,
        "masked_secrets": masked,
        "summary": summary,
    }


@debug_tool(
    "get_django_urls",
    "List all Django URL patterns with name, pattern, and callback",
)
def get_django_urls() -> dict:
    if not _django_configured():
        return {"error": "Django is not installed or settings are not configured"}

    from django.conf import settings
    from django.urls import URLPattern, URLResolver, get_resolver

    root = getattr(settings, "ROOT_URLCONF", None)
    resolver = get_resolver()

    patterns: list[dict[str, Any]] = []

    def _walk(url_patterns, prefix: str = ""):
        for entry in url_patterns:
            try:
                if isinstance(entry, URLResolver):
                    child_prefix = entry.pattern.describe() if hasattr(entry.pattern, "describe") else ""
                    _walk(entry.url_patterns, prefix + (child_prefix or ""))
                    continue
            except Exception:
                pass

            if isinstance(entry, URLPattern):
                callback = getattr(entry, "callback", None)
                try:
                    pattern_str = entry.pattern.describe()
                except Exception:
                    pattern_str = str(getattr(entry, "pattern", ""))
                try:
                    name = entry.name
                except Exception:
                    name = None
                patterns.append({
                    "name": name,
                    "pattern": (prefix + pattern_str) if pattern_str else prefix,
                    "callback": _describe_callback(callback),
                })

    try:
        _walk(resolver.url_patterns)
    except Exception as exc:
        return {"error": f"Failed to walk URL patterns: {exc}", "root_urlconf": root}

    return {
        "root_urlconf": root,
        "pattern_count": len(patterns),
        "patterns": patterns[:500],
    }


def _describe_callback(callback: Any) -> str:
    """Render a URL callback as a dotted module path where possible."""
    if callback is None:
        return ""
    view_class = getattr(callback, "view_class", None)
    if view_class is not None:
        module = getattr(view_class, "__module__", "")
        qualname = getattr(view_class, "__qualname__", getattr(view_class, "__name__", ""))
        return f"{module}.{qualname}" if module else qualname
    module = getattr(callback, "__module__", "")
    qualname = getattr(callback, "__qualname__", getattr(callback, "__name__", str(callback)))
    return f"{module}.{qualname}" if module else qualname


@debug_tool(
    "get_django_models",
    "List all Django models with app label, model name, fields, and db_table",
)
def get_django_models() -> dict:
    if not _django_configured():
        return {"error": "Django is not installed or settings are not configured"}

    try:
        from django.apps import apps
    except Exception as exc:
        return {"error": f"Could not import django.apps: {exc}"}

    models_info: list[dict[str, Any]] = []
    for model in apps.get_models():
        fields: list[dict[str, Any]] = []
        try:
            for field in model._meta.get_fields():
                fields.append({
                    "name": field.name,
                    "type": type(field).__name__,
                    "internal_type": getattr(field, "get_internal_type", lambda: "")(),
                })
        except Exception:
            # Best effort: fall back to concrete fields only.
            for field in model._meta.concrete_fields:
                fields.append({
                    "name": field.name,
                    "type": type(field).__name__,
                })

        models_info.append({
            "app_label": model._meta.app_label,
            "model_name": model._meta.model_name,
            "object_name": model._meta.object_name,
            "db_table": model._meta.db_table,
            "field_count": len(fields),
            "fields": fields,
        })

    return {
        "app_count": len({m["app_label"] for m in models_info}),
        "model_count": len(models_info),
        "models": models_info,
    }


@debug_tool(
    "get_django_cache",
    "Inspect Django cache backends: backend type, location, and key info",
)
def get_django_cache() -> dict:
    if not _django_configured():
        return {"error": "Django is not installed or settings are not configured"}

    from django.conf import settings

    caches_config = getattr(settings, "CACHES", {}) or {}
    backends: list[dict[str, Any]] = []
    for alias, cfg in caches_config.items():
        cfg = dict(cfg) if isinstance(cfg, dict) else {}
        backend = cfg.get("BACKEND", "")
        location = cfg.get("LOCATION", "")
        info: dict[str, Any] = {
            "alias": alias,
            "backend": backend,
            "backend_type": backend.rsplit(".", 1)[-1] if backend else "",
            "location": location,
            "options": dict(cfg.get("OPTIONS", {}) or {}),
            "key_prefix": cfg.get("KEY_PREFIX", ""),
            "timeout": cfg.get("TIMEOUT", None),
        }

        # Best-effort live stats from the actual cache instance.
        try:
            from django.core.cache import caches
            cache = caches[alias]
            info["class"] = type(cache).__name__
            try:
                info["stats"] = cache._cache.stats()
            except Exception:
                pass
            try:
                info["key_count"] = len(cache._cache.keys())
            except Exception:
                pass
        except Exception:
            pass

        backends.append(info)

    return {
        "cache_count": len(backends),
        "caches": backends,
    }
