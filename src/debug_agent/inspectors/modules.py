"""Module inspector: loaded modules, import stats, module details."""

from __future__ import annotations

import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


@debug_tool(
    "get_loaded_modules",
    "List loaded Python modules (sys.modules) with their versions",
)
def get_loaded_modules(prefix: str = ToolParam("Filter by module name prefix (empty = all)", required=False)) -> dict:
    results = []
    for name in sorted(sys.modules.keys()):
        if prefix and not name.lower().startswith(prefix.lower()):
            continue
        mod = sys.modules.get(name)
        if mod is None:
            results.append({"name": name, "version": None, "loaded": False})
            continue

        version = getattr(mod, "__version__", None)
        if not version:
            # Try importlib.metadata for installed packages
            try:
                from importlib.metadata import version as get_version
                # Handle submodules by taking the top-level package
                top_pkg = name.split(".")[0]
                version = get_version(top_pkg)
            except Exception:
                version = None

        results.append({"name": name, "version": version, "file": getattr(mod, "__file__", None)})

    return {"total": len(results), "modules": results}


@debug_tool(
    "get_import_stats",
    "Get module import statistics: total count, largest modules by file size",
)
def get_import_stats() -> dict:
    import os

    module_sizes = []
    total = 0
    builtin_count = 0

    for name, mod in sys.modules.items():
        if mod is None:
            continue
        total += 1
        filepath = getattr(mod, "__file__", None)
        if filepath and os.path.isfile(filepath):
            try:
                size = os.path.getsize(filepath)
                module_sizes.append((name, size, filepath))
            except OSError:
                pass
        else:
            builtin_count += 1

    module_sizes.sort(key=lambda x: -x[1])
    largest = [
        {"name": name, "size_kb": round(size / 1024, 2), "file": filepath}
        for name, size, filepath in module_sizes[:20]
    ]

    return {
        "total_modules": total,
        "builtin_or_builtin_like": builtin_count,
        "with_file_path": len(module_sizes),
        "largest_modules": largest,
    }


@debug_tool(
    "get_module_detail",
    "Get detailed information about a specific loaded module",
)
def get_module_detail(module_name: str = ToolParam("The module name to inspect (e.g. 'flask', 'debug_agent.engine')")) -> dict:
    mod = sys.modules.get(module_name)
    if mod is None:
        return {"error": f"Module '{module_name}' is not loaded"}

    import os
    filepath = getattr(mod, "__file__", None)
    file_size = None
    if filepath and os.path.isfile(filepath):
        try:
            file_size = os.path.getsize(filepath)
        except OSError:
            pass

    version = getattr(mod, "__version__", None)
    if not version:
        try:
            from importlib.metadata import version as get_version
            version = get_version(module_name.split(".")[0])
        except Exception:
            pass

    # Get public attributes
    public_attrs = []
    for attr in sorted(dir(mod)):
        if attr.startswith("_"):
            continue
        try:
            obj = getattr(mod, attr)
            public_attrs.append({
                "name": attr,
                "type": type(obj).__name__,
            })
        except Exception:
            continue

    return {
        "name": module_name,
        "file": filepath,
        "file_size_bytes": file_size,
        "version": version,
        "package": getattr(mod, "__package__", None),
        "spec": str(getattr(mod, "__spec__", None)),
        "public_attribute_count": len(public_attrs),
        "public_attributes": public_attrs[:50],
    }
