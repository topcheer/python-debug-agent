"""Flask extension inspector: blueprints, config, and Jinja2 template filters.

These tools introspect the active Flask app via ``flask.current_app`` when
possible, falling back to walking loaded modules for a ``flask.Flask``
instance. They degrade gracefully when Flask is not installed.
"""

from __future__ import annotations

import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Helpers ─────────────────────────────────────────────────────────────────


_SECRET_HINTS = ("KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL", "API")


def _is_secret_key(key: str) -> bool:
    upper = key.upper()
    return any(hint in upper for hint in _SECRET_HINTS)


def _mask_value(value: Any) -> Any:
    if isinstance(value, str) and value:
        return "***masked***" if len(value) > 4 else "***"
    return value


def _find_flask_app():
    """Resolve the active Flask app.

    Order:
      1. ``flask.current_app`` (works inside a request / app context)
      2. Walk loaded modules for a ``flask.Flask`` instance
    """
    try:
        import flask
    except ImportError:
        return None

    try:
        app = flask.current_app
        if app is not None and getattr(app, "_got_first_request", None) is not None:
            # current_app exists inside an app context; this proxy is truthy
            # only when there is an active app.
            return app._get_current_object()
    except Exception:
        pass

    for mod in list(sys.modules.values()):
        if mod is None or mod.__name__.startswith("debug_agent"):
            continue
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            try:
                obj = getattr(mod, attr_name)
                if isinstance(obj, flask.Flask):
                    return obj
            except Exception:
                continue
    return None


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_flask_blueprints",
    "List registered Flask blueprints with their routes",
)
def get_flask_blueprints() -> dict:
    app = _find_flask_app()
    if app is None:
        return {"error": "Flask is not installed or no Flask app was found"}

    blueprints: list[dict[str, Any]] = []
    for name, bp in app.blueprints.items():
        routes: list[dict[str, Any]] = []
        for rule in app.url_map.iter_rules():
            endpoint = rule.endpoint
            # Blueprint rules have endpoints formatted as "blueprint_name.view".
            if endpoint.startswith(f"{name}."):
                view_name = endpoint.split(".", 1)[1]
                routes.append({
                    "rule": str(rule),
                    "endpoint": endpoint,
                    "view": view_name,
                    "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
                })

        blueprints.append({
            "name": name,
            "import_name": getattr(bp, "import_name", None),
            "url_prefix": getattr(bp, "url_prefix", None),
            "static_folder": getattr(bp, "static_folder", None),
            "template_folder": getattr(bp, "template_folder", None),
            "route_count": len(routes),
            "routes": routes,
        })

    return {
        "blueprint_count": len(blueprints),
        "blueprints": blueprints,
    }


@debug_tool(
    "get_flask_config",
    "Get Flask config values with secrets masked",
)
def get_flask_config() -> dict:
    app = _find_flask_app()
    if app is None:
        return {"error": "Flask is not installed or no Flask app was found"}

    config = app.config
    safe: dict[str, Any] = {}

    for key in config:
        value = config[key]
        if _is_secret_key(key):
            safe[key] = _mask_value(value)
        elif isinstance(value, str) and value:
            # Also mask inline credentials in connection-string-like values.
            low = key.upper()
            if "URL" in low or "URI" in low or "DATABASE" in low or "DSN" in low:
                safe[key] = _mask_value(value)
            else:
                safe[key] = value
        else:
            safe[key] = value

    debug_mode = bool(config.get("DEBUG"))
    testing_mode = bool(config.get("TESTING"))
    env = config.get("ENV") or config.get("FLASK_ENV", None)

    return {
        "config_count": len(safe),
        "debug": debug_mode,
        "testing": testing_mode,
        "env": env,
        "config": safe,
    }


@debug_tool(
    "get_flask_template_filters",
    "List registered Jinja2 template filters on the Flask app",
)
def get_flask_template_filters() -> dict:
    app = _find_flask_app()
    if app is None:
        return {"error": "Flask is not installed or no Flask app was found"}

    jinja_env = app.jinja_env
    filters = {}
    for name, func in jinja_env.filters.items():
        filters[name] = {
            "module": getattr(func, "__module__", None),
            "qualname": getattr(func, "__qualname__", getattr(func, "__name__", repr(func))),
        }

    return {
        "filter_count": len(filters),
        "filters": filters,
    }
