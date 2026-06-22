"""Security inspector: auth configurations, active sessions, and CORS.

Register auth configs and session stores at runtime:

    from debug_agent.inspectors.security_inspector import (
        register_auth_config, register_session_store,
    )
    register_auth_config("api_key", {"scheme": "api_key", ...})
    register_session_store("flask_session", my_session_backend)
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration registries ──────────────────────────────────────────────────

_auth_configs: dict[str, Any] = {}
_session_stores: dict[str, Any] = {}


def register_auth_config(name: str, config: Any) -> None:
    """Register an authentication configuration under *name*."""
    _auth_configs[name] = config


def register_session_store(name: str, store: Any) -> None:
    """Register a session backend under *name* so the inspector can query it."""
    _session_stores[name] = store


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _detect_scheme_type(config: Any) -> str:
    """Best-effort label for the auth scheme type."""
    if isinstance(config, dict):
        explicit = config.get("scheme") or config.get("type")
        if explicit:
            return str(explicit)
    cls = type(config).__name__.lower()
    for needle in ("jwt", "login", "basic", "apikey", "oauth", "token", "session"):
        if needle in cls:
            return needle
    return type(config).__name__


def _has_secret(config: Any) -> bool:
    """Return True if a secret-like key is present (value is never exposed)."""
    _SECRET_KEYS = (
        "secret", "secret_key", "api_key", "token", "password",
        "private_key", "signing_key",
    )
    if isinstance(config, dict):
        return any(
            bool(config.get(k))
            for k in _SECRET_KEYS
        )
    return any(getattr(config, k, None) for k in _SECRET_KEYS)


def _extract_token_expiry(config: Any) -> Any:
    for key in ("token_expiry", "expiry", "expires_in", "token_expiration", "exp"):
        if isinstance(config, dict):
            if key in config:
                return config[key]
        else:
            val = getattr(config, key, None)
            if val is not None:
                return val
    return None


def _summarise_auth_config(name: str, config: Any) -> dict:
    return {
        "name": name,
        "scheme_type": _detect_scheme_type(config),
        "token_expiry": _extract_token_expiry(config),
        "secret_present": _has_secret(config),
    }


def _query_session_store(name: str, store: Any) -> list[dict] | dict:
    """Try several common interfaces to extract sessions from *store*."""
    # Callable returning a list of sessions
    if callable(store):
        try:
            result = store()
            if isinstance(result, list):
                return result
            if isinstance(result, dict) and "sessions" in result:
                return result["sessions"]
        except Exception:
            pass

    # Objects with an explicit method
    for method in ("active_sessions", "get_sessions", "all_sessions", "list_sessions"):
        fn = getattr(store, method, None)
        if callable(fn):
            try:
                return list(fn())
            except Exception:
                continue

    # Dict-of-sessions store
    if isinstance(store, dict):
        sessions = []
        for sid, data in store.items():
            sessions.append(_normalise_session(sid, data))
        return sessions

    return {"name": name, "error": "Unsupported session store interface"}


def _normalise_session(sid: Any, data: Any) -> dict:
    if isinstance(data, dict):
        return {
            "session_id": str(sid),
            "user": data.get("user") or data.get("username") or data.get("user_id"),
            "created": data.get("created") or data.get("created_at"),
            "last_access": data.get("last_access") or data.get("last_activity") or data.get("updated"),
            "ip": data.get("ip") or data.get("remote_addr") or data.get("ip_address"),
        }
    return {"session_id": str(sid), "data": str(data)}


def _detect_cors_from_frameworks() -> dict | None:
    """Auto-detect CORS configuration from common Flask / FastAPI / Django middleware."""
    # Flask-CORS
    try:
        import flask  # type: ignore

        # Flask-CORS stores its config on the extension object
        for ext_name in ("cors", "CORS"):
            for ref in _iter_flask_extensions():
                if hasattr(ref, "_options") or type(ref).__module__.startswith("flask_cors"):
                    opts = getattr(ref, "_options", {}) or {}
                    resources = getattr(ref, "resources", {})
                    return {
                        "source": "Flask-CORS",
                        "origins": opts.get("origins", resources.get("origins", [])),
                        "methods": opts.get("methods"),
                        "allow_headers": opts.get("allow_headers"),
                        "expose_headers": opts.get("expose_headers"),
                        "supports_credentials": opts.get("supports_credentials"),
                        "max_age": opts.get("max_age"),
                    }
    except Exception:
        pass

    # Django CORS headers
    try:
        from django.conf import settings  # type: ignore

        if getattr(settings, "CONFIGURED", False):
            return {
                "source": "django-cors-headers",
                "origins": list(getattr(settings, "CORS_ALLOWED_ORIGINS", []) or []),
                "allow_all": getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False),
                "methods": list(getattr(settings, "CORS_ALLOW_METHODS", []) or []),
                "allow_headers": list(getattr(settings, "CORS_ALLOW_HEADERS", []) or []),
                "allow_credentials": getattr(settings, "CORS_ALLOW_CREDENTIALS", False),
            }
    except Exception:
        pass

    return None


def _iter_flask_extensions():
    """Yield Flask extension objects from any Flask app in scope."""
    try:
        import flask  # type: ignore
        ctx = flask.current_app
        if ctx is not None:
            yield from getattr(ctx, "extensions", {}).values()
    except Exception:
        pass


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_auth_config",
    "List registered authentication configurations (scheme type, token expiry, secret present)",
)
def get_auth_config() -> dict:
    if not _auth_configs:
        return {
            "registered": [],
            "count": 0,
            "message": "No auth configs registered. Use register_auth_config(name, config).",
        }
    return {
        "count": len(_auth_configs),
        "configs": [_summarise_auth_config(name, cfg) for name, cfg in _auth_configs.items()],
    }


@debug_tool(
    "get_active_sessions",
    "List active user sessions from registered session backends",
)
def get_active_sessions() -> dict:
    if not _session_stores:
        return {
            "stores": [],
            "total_sessions": 0,
            "message": "No session stores registered. Use register_session_store(name, store).",
        }

    all_sessions: list[dict] = []
    stores_summary: list[dict] = []
    for store_name, store in _session_stores.items():
        result = _query_session_store(store_name, store)
        if isinstance(result, list):
            all_sessions.extend(result)
            stores_summary.append({"name": store_name, "sessions": len(result)})
        else:
            stores_summary.append(result)

    return {
        "total_sessions": len(all_sessions),
        "stores": stores_summary,
        "sessions": all_sessions,
    }


@debug_tool(
    "get_cors_config",
    "Show CORS configuration: allowed origins, methods, headers, credentials",
)
def get_cors_config() -> dict:
    detected = _detect_cors_from_frameworks()
    if detected:
        return {"detected": True, **detected}

    return {
        "detected": False,
        "message": (
            "No CORS configuration auto-detected. Register one via "
            "register_auth_config('cors', {...}) or install Flask-CORS / "
            "django-cors-headers."
        ),
    }
