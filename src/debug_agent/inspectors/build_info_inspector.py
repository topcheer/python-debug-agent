"""Build / deployment info inspector: Python build details, runtime versions, deployment metadata."""

from __future__ import annotations

import os
import platform
import socket
import sys
import time
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Helpers ──────────────────────────────────────────────────────────────────


_PROCESS_START = time.time()


_ENV_VARS_OF_INTEREST = [
    "APP_ENV",
    "FLASK_ENV",
    "DJANGO_SETTINGS_MODULE",
    "NODE_ENV",
    "ENVIRONMENT",
    "STAGE",
]


_RUNTIME_DEPS = [
    "flask",
    "django",
    "fastapi",
    "sqlalchemy",
    "redis",
    "celery",
    "psycopg2",
    "pymongo",
    "uvicorn",
    "gunicorn",
    "requests",
    "aiohttp",
    "pydantic",
]


def _detect_container() -> dict[str, Any]:
    """Detect whether the process runs inside a container."""
    container_type = None

    if os.path.exists("/.dockerenv"):
        container_type = "docker"
    elif os.path.exists("/run/.containerenv"):
        container_type = "podman"
    else:
        try:
            with open("/proc/1/cgroup", "r") as f:
                content = f.read()
                if "docker" in content:
                    container_type = "docker"
                elif "kubepods" in content:
                    container_type = "kubernetes"
                elif "lxc" in content:
                    container_type = "lxc"
        except (FileNotFoundError, IOError, OSError):
            pass

    return {
        "in_container": container_type is not None,
        "container_type": container_type,
    }


def _get_uptime() -> float:
    """Return process uptime in seconds."""
    return round(time.time() - _PROCESS_START, 2)


def _get_package_versions() -> dict[str, str | None]:
    """Return versions of installed packages via importlib.metadata."""
    try:
        from importlib.metadata import version as get_version, PackageNotFoundError
    except ImportError:
        return {}

    result = {}
    for pkg in _RUNTIME_DEPS:
        try:
            result[pkg] = get_version(pkg)
        except PackageNotFoundError:
            pass
        except Exception:
            pass
    return result


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_build_info",
    "Get Python build details: version, implementation, build date, compiler, C API version",
)
def get_build_info() -> dict:
    info: dict[str, Any] = {
        "python_version": sys.version,
        "version_info": {
            "major": sys.version_info[0],
            "minor": sys.version_info[1],
            "micro": sys.version_info[2],
            "releaselevel": sys.version_info[3],
            "serial": sys.version_info[4],
        },
        "implementation": platform.python_implementation(),
        "compiler": platform.python_compiler(),
        "build_date": platform.python_build()[1] if len(platform.python_build()) > 1 else None,
        "build_info_raw": platform.python_build()[0] if platform.python_build() else None,
        "api_version": sys.api_version,
        "hexversion": hex(sys.hexversion),
    }

    # C API version
    try:
        info["c_api_version"] = sys.api_version
    except AttributeError:
        pass

    # Try to get installed package versions
    pkg_versions = _get_package_versions()
    if pkg_versions:
        info["installed_packages"] = pkg_versions

    return info


@debug_tool(
    "get_deployment_info",
    "Get deployment metadata: hostname, PID, uptime, container detection, platform, selected env vars",
)
def get_deployment_info() -> dict:
    container = _detect_container()

    selected_env: dict[str, str | None] = {}
    for var in _ENV_VARS_OF_INTEREST:
        selected_env[var] = os.environ.get(var)

    return {
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "uptime_seconds": _get_uptime(),
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "processor": platform.processor() or None,
        "container_detected": container["in_container"],
        "container_type": container["container_type"],
        "working_directory": os.getcwd(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME"),
        "environment_variables": {k: v for k, v in selected_env.items() if v is not None},
    }


@debug_tool(
    "get_runtime_version",
    "Get versions of key runtime dependencies (flask, django, fastapi, sqlalchemy, redis, celery, etc.)",
)
def get_runtime_version() -> dict:
    pkg_versions = _get_package_versions()

    # Also try importing for modules that expose __version__
    import_versions: dict[str, str | None] = {}
    for dep in _RUNTIME_DEPS:
        mod = sys.modules.get(dep)
        if mod is not None:
            ver = getattr(mod, "__version__", None)
            if ver:
                import_versions[dep] = ver

    # Merge: prefer importlib.metadata, fall back to __version__
    merged: dict[str, str | None] = {}
    for dep in _RUNTIME_DEPS:
        merged[dep] = pkg_versions.get(dep) or import_versions.get(dep)

    installed = {k: v for k, v in merged.items() if v is not None}
    not_installed = [k for k, v in merged.items() if v is None]

    return {
        "installed": installed,
        "not_installed": not_installed,
        "total_checked": len(_RUNTIME_DEPS),
        "total_installed": len(installed),
    }
