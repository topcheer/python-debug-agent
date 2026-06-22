"""Jinja2 inspector: environment info and loaded templates.

These tools introspect any Jinja2 ``Environment`` reachable via the active
Flask app (``app.jinja_env``) or by walking loaded modules for a Jinja2
environment. They degrade gracefully when Jinja2 is not installed.
"""

from __future__ import annotations

import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Helpers ─────────────────────────────────────────────────────────────────


def _jinja2_available() -> bool:
    try:
        import jinja2  # noqa: F401
        return True
    except ImportError:
        return False


def _find_jinja_env() -> Any | None:
    """Resolve a Jinja2 Environment to inspect.

    Order:
      1. The active Flask app's ``jinja_env``
      2. Any ``jinja2.Environment`` found in loaded modules
    """
    if not _jinja2_available():
        return None

    try:
        import flask
        import jinja2
    except ImportError:
        jinja2 = None
        flask = None

    if flask is not None:
        try:
            app = flask.current_app
            if app is not None and getattr(app, "_got_first_request", None) is not None:
                env = app._get_current_object().jinja_env
                return env
        except Exception:
            pass

        # Fall back to walking modules for a Flask app.
        for mod in list(sys.modules.values()):
            if mod is None or mod.__name__.startswith("debug_agent"):
                continue
            for attr_name in dir(mod):
                if attr_name.startswith("_"):
                    continue
                try:
                    obj = getattr(mod, attr_name)
                    if isinstance(obj, flask.Flask):
                        return obj.jinja_env
                except Exception:
                    continue

    if jinja2 is not None:
        for mod in list(sys.modules.values()):
            if mod is None or mod.__name__.startswith("debug_agent"):
                continue
            for attr_name in dir(mod):
                if attr_name.startswith("_"):
                    continue
                try:
                    obj = getattr(mod, attr_name)
                    if isinstance(obj, jinja2.Environment):
                        return obj
                except Exception:
                    continue

    return None


def _describe_callable(value: Any) -> dict[str, Any]:
    """Describe a Jinja global/filter/test value safely.

    Flask injects ``request`` / ``session`` / ``g`` proxies into the globals;
    touching attributes on those proxies (e.g. ``__module__``) outside a
    request context raises ``RuntimeError``. We guard every attribute access
    so one proxy can't break the whole introspection.
    """
    info: dict[str, Any] = {"type": type(value).__name__}
    for attr in ("module", "qualname"):
        try:
            py_attr = "__module__" if attr == "module" else "__qualname__"
            resolved = getattr(value, py_attr, None)
            if resolved is None and attr == "qualname":
                resolved = getattr(value, "__name__", None)
            info[attr] = resolved
        except Exception:
            info[attr] = None
    return info


# Tools ----------------------------------------------------------------------


@debug_tool(
    "get_jinja_env",
    "Get Jinja2 environment info: loaded templates, filters, tests, and globals",
)
def get_jinja_env() -> dict:
    env = _find_jinja_env()
    if env is None:
        return {"error": "Jinja2 is not installed or no environment was found"}

    loader = env.loader
    loader_info: dict[str, Any] = {
        "type": type(loader).__name__ if loader is not None else None,
    }
    if loader is not None:
        # FileSystemLoader exposes the search paths.
        searchpath = getattr(loader, "searchpath", None)
        if searchpath is not None:
            loader_info["searchpath"] = list(searchpath)

    autoescape = env.autoescape
    # autoescape can be a callable; report truthiness plus repr.
    try:
        autoescape_value = bool(autoescape)
    except Exception:
        autoescape_value = None

    globals_map = {}
    for name, value in env.globals.items():
        globals_map[name] = _describe_callable(value)

    filters_map = {}
    for name, func in env.filters.items():
        filters_map[name] = _describe_callable(func)

    tests_map = {}
    for name, func in env.tests.items():
        tests_map[name] = _describe_callable(func)

    loaded_templates = []
    try:
        cache = getattr(env, "cache", None)
        if cache is not None:
            # Jinja2's LRUCache supports iteration over keys.
            for key in list(cache):
                loaded_templates.append(str(key))
    except Exception:
        pass

    return {
        "environment_type": type(env).__name__,
        "autoescape": autoescape_value,
        "trim_blocks": getattr(env, "trim_blocks", None),
        "lstrip_blocks": getattr(env, "lstrip_blocks", None),
        "undefined": type(env.undefined).__name__,
        "loader": loader_info,
        "global_count": len(globals_map),
        "filter_count": len(filters_map),
        "test_count": len(tests_map),
        "loaded_template_count": len(loaded_templates),
        "globals": globals_map,
        "filters": filters_map,
        "tests": tests_map,
        "loaded_templates": loaded_templates,
    }


@debug_tool(
    "get_jinja_templates",
    "List all loaded Jinja2 templates with their file paths",
)
def get_jinja_templates() -> dict:
    env = _find_jinja_env()
    if env is None:
        return {"error": "Jinja2 is not installed or no environment was found"}

    templates: list[dict[str, Any]] = []
    cache = getattr(env, "cache", None)
    if cache is None:
        return {
            "message": "No template cache available on this environment",
            "template_count": 0,
            "templates": [],
        }

    seen = set()
    try:
        for key in list(cache):
            if key in seen:
                continue
            seen.add(key)
            entry: dict[str, Any] = {"name": str(key)}
            template = cache.get(key)
            if template is not None:
                filename = getattr(template, "filename", None)
                if filename:
                    entry["path"] = filename
                module = getattr(template, "_module", None)
                if module is not None:
                    entry["module"] = getattr(module, "__name__", str(module))
            templates.append(entry)
    except Exception:
        pass

    return {
        "template_count": len(templates),
        "templates": templates,
    }
