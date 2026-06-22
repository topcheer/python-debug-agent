"""FastAPI inspector: OpenAPI schema and Pydantic model introspection.

Register a FastAPI app at runtime so the inspector can reach it:

    from debug_agent.inspectors.fastapi_ext import register_fastapi_app
    register_fastapi_app("my_app", app)
"""

from __future__ import annotations

import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ────────────────────────────────────────────────────────────

_registered_apps: dict[str, Any] = {}


def register_fastapi_app(name: str, app: Any) -> None:
    """Register a FastAPI app instance under a name."""
    _registered_apps[name] = app


def _fastapi_available() -> bool:
    try:
        import fastapi  # noqa: F401
        return True
    except ImportError:
        return False


def _find_fastapi_apps() -> dict[str, Any]:
    """Return registered apps plus any discovered in loaded modules."""
    apps = dict(_registered_apps)

    try:
        import fastapi
    except ImportError:
        return apps

    for mod in list(sys.modules.values()):
        if mod is None or mod.__name__.startswith("debug_agent"):
            continue
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            try:
                obj = getattr(mod, attr_name)
                if isinstance(obj, fastapi.FastAPI):
                    key = f"{mod.__name__}.{attr_name}"
                    if key not in apps:
                        apps[key] = obj
            except Exception:
                continue
    return apps


# ─── Pydantic helpers ────────────────────────────────────────────────────────


def _describe_pydantic_model(model_cls: Any) -> dict[str, Any]:
    """Return field metadata for a Pydantic v2 (or v1) model class."""
    fields: dict[str, Any] = {}

    # Pydantic v2: model_fields
    model_fields = getattr(model_cls, "model_fields", None)
    if model_fields:
        for fname, finfo in model_fields.items():
            entry: dict[str, Any] = {}
            annotation = getattr(finfo, "annotation", None)
            entry["type"] = str(annotation) if annotation is not None else None
            entry["default"] = repr(getattr(finfo, "default", None))
            entry["required"] = getattr(finfo, "is_required", lambda: True)()
            fields[fname] = entry
        return {"name": model_cls.__name__, "pydantic": "v2", "fields": fields}

    # Pydantic v1: __fields__
    v1_fields = getattr(model_cls, "__fields__", None)
    if v1_fields:
        for fname, finfo in v1_fields.items():
            entry = {
                "type": str(finfo.outer_type_) if hasattr(finfo, "outer_type_") else None,
                "required": bool(getattr(finfo, "required", True)),
            }
            default = getattr(finfo, "default", None)
            entry["default"] = repr(default)
            fields[fname] = entry
        return {"name": model_cls.__name__, "pydantic": "v1", "fields": fields}

    return {"name": getattr(model_cls, "__name__", str(model_cls)), "fields": {}}


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_fastapi_openapi",
    "Get FastAPI OpenAPI schema and Pydantic models with field types from registered apps",
)
def get_fastapi_openapi(
    name: str = ToolParam("App name (omit to list all registered apps)", required=False),
) -> dict:
    if not _fastapi_available():
        return {"error": "FastAPI is not installed"}

    apps = _find_fastapi_apps()
    if not apps:
        return {
            "message": "No FastAPI apps registered. Call register_fastapi_app(name, app) to register one.",
            "registered_count": 0,
        }

    if name:
        app = apps.get(name)
        if app is None:
            return {
                "error": f"No FastAPI app found with name '{name}'",
                "available": list(apps.keys()),
            }
        return _inspect_app(name, app)

    if len(apps) == 1:
        n, a = next(iter(apps.items()))
        return _inspect_app(n, a)

    return {
        "registered_count": len(apps),
        "apps": list(apps.keys()),
        "message": "Multiple apps found. Specify 'name' to inspect one.",
    }


def _inspect_app(name: str, app: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"app": name}

    # OpenAPI schema
    try:
        result["openapi_version"] = getattr(app, "openapi_version", None)
        result["title"] = getattr(app, "title", None)
        result["version"] = getattr(app, "version", None)

        get_schema = getattr(app, "openapi", None)
        if callable(get_schema):
            schema = get_schema()
            result["path_count"] = len(schema.get("paths", {})) if isinstance(schema, dict) else 0
            result["openapi_schema"] = schema
    except Exception as exc:
        result["openapi_error"] = str(exc)

    # Routes summary (lighter than full schema)
    try:
        routes = []
        for route in app.routes:
            methods = getattr(route, "methods", None) or set()
            routes.append(
                {
                    "path": getattr(route, "path", None),
                    "methods": sorted(methods) if methods else [],
                    "name": getattr(route, "name", None),
                    "endpoint": getattr(getattr(route, "endpoint", None), "__name__", None),
                }
            )
        result["routes"] = routes
        result["route_count"] = len(routes)
    except Exception as exc:
        result["routes_error"] = str(exc)

    # Pydantic models referenced by the app
    try:
        models = []
        for route in app.routes:
            endpoint = getattr(route, "endpoint", None)
            if endpoint is None:
                continue
            # Inspect body param type hints for BaseModel subclasses
            try:
                import typing

                hints = typing.get_type_hints(endpoint)
            except Exception:
                hints = {}

            import inspect as pyinspect

            sig = pyinspect.signature(endpoint)
            for pname, param in sig.parameters.items():
                if pname in ("self", "request", "response"):
                    continue
                ann = hints.get(pname, None)
                model_cls = _resolve_model_class(ann)
                if model_cls is not None and model_cls not in [m.get("_cls") for m in models]:
                    models.append({**_describe_pydantic_model(model_cls), "_cls": model_cls})

        # Strip the internal _cls key
        for m in models:
            m.pop("_cls", None)
        result["pydantic_models"] = models
        result["model_count"] = len(models)
    except Exception as exc:
        result["models_error"] = str(exc)

    return result


def _resolve_model_class(ann: Any) -> Any:
    """Return a Pydantic BaseModel subclass from an annotation, or None."""
    try:
        from pydantic import BaseModel
    except ImportError:
        return None

    if ann is None:
        return None
    if isinstance(ann, type) and issubclass(ann, BaseModel):
        return ann

    # Handle typing constructs like Optional[Model], Body(...)
    args = getattr(ann, "__args__", None)
    if args:
        for arg in args:
            if isinstance(arg, type) and issubclass(arg, BaseModel):
                return arg
    return None
