"""Framework inspector: routes, middleware, dependency injection."""

from __future__ import annotations

import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


def _find_app():
    """Find the main web framework app instance."""
    # Try FastAPI / Starlette
    try:
        import fastapi
        for obj in _walk_module_objects():
            if isinstance(obj, fastapi.FastAPI):
                return ("fastapi", obj)
    except ImportError:
        pass

    # Try Flask
    try:
        import flask
        for obj in _walk_module_objects():
            if isinstance(obj, flask.Flask):
                return ("flask", obj)
    except ImportError:
        pass

    return (None, None)


def _walk_module_objects():
    """Walk loaded modules looking for app instances."""
    seen = set()
    for mod in list(sys.modules.values()):
        if mod is None or mod.__name__.startswith("debug_agent"):
            continue
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            try:
                obj = getattr(mod, attr_name)
                if id(obj) not in seen:
                    seen.add(id(obj))
                    yield obj
            except Exception:
                continue


@debug_tool("get_routes", "List all registered web routes/endpoints with methods and paths")
def get_routes() -> dict:
    ftype, app = _find_app()
    if not app:
        return {"error": "No supported web framework app found"}

    routes = []
    if ftype == "fastapi":
        for route in app.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                routes.append({
                    "path": route.path,
                    "methods": list(route.methods or set()),
                    "name": getattr(route, "name", ""),
                    "endpoint": getattr(route, "endpoint", "").__name__ if hasattr(getattr(route, "endpoint", ""), "__name__") else "",
                })
    elif ftype == "flask":
        for rule in app.url_map.iter_rules():
            routes.append({
                "path": str(rule),
                "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
                "endpoint": rule.endpoint,
            })

    return {"framework": ftype, "route_count": len(routes), "routes": routes}


@debug_tool("get_middleware", "List registered middleware (FastAPI/Starlette/FastAPI)")
def get_middleware() -> dict:
    ftype, app = _find_app()
    if not app:
        return {"error": "No supported web framework app found"}

    middlewares = []
    if ftype == "fastapi":
        try:
            mw_stack = app.user_middleware
            middlewares = [str(m) for m in mw_stack]
        except Exception:
            pass
    elif ftype == "flask":
        middlewares = []  # Flask doesn't have middleware in the same way

    return {"framework": ftype, "middlewares": middlewares}


@debug_tool("get_installed_packages", "List installed Python packages")
def get_installed_packages(prefix: str = ToolParam("Filter by prefix (empty = all)", required=False)) -> dict:
    try:
        import pkg_resources
        pkgs = sorted(
            [(p.project_name, p.version) for p in pkg_resources.working_set],
            key=lambda x: x[0].lower(),
        )
        if prefix:
            pkgs = [(n, v) for n, v in pkgs if n.lower().startswith(prefix.lower())]
        return {"total": len(pkgs), "packages": [{"name": n, "version": v} for n, v in pkgs]}
    except ImportError:
        from importlib.metadata import distributions
        pkgs = sorted(
            [(d.metadata["Name"], d.version) for d in distributions()],
            key=lambda x: x[0].lower(),
        )
        if prefix:
            pkgs = [(n, v) for n, v in pkgs if n.lower().startswith(prefix.lower())]
        return {"total": len(pkgs), "packages": [{"name": n, "version": v} for n, v in pkgs]}


@debug_tool("get_environment_variables", "List environment variables (filtered)")
def get_environment_variables(prefix: str = ToolParam("Filter by prefix (e.g. 'PATH')", required=False)) -> dict:
    import os
    env = dict(os.environ)
    if prefix:
        env = {k: v for k, v in env.items() if k.upper().startswith(prefix.upper())}
    # Mask potential secrets
    masked = {}
    for k, v in env.items():
        if any(s in k.upper() for s in ["KEY", "SECRET", "PASSWORD", "TOKEN", "CREDENTIAL"]):
            masked[k] = "***masked***"
        else:
            masked[k] = v
    return {"variables": masked, "count": len(masked)}
