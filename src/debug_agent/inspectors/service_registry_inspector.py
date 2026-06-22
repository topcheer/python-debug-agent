"""Service registry inspector: enumerate registered debug tools and loaded project modules."""

from __future__ import annotations

import sys
import sysconfig
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam, registry


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _get_stdlib_paths() -> set[str]:
    """Return common standard-library installation paths to exclude."""
    paths = set()
    for key in ("stdlib", "platstdlib", "platlib"):
        p = sysconfig.get_path(key)
        if p:
            paths.add(os_path_norm(p))
    # Also exclude built-in modules directory
    p = sysconfig.get_path("purelib")
    if p:
        paths.add(os_path_norm(p))
    return paths


def os_path_norm(path: str) -> str:
    """Normalise a path for comparison (case-insensitive on some platforms)."""
    import os
    return os.path.normpath(path)


def _is_stdlib_module(mod_name: str, mod: Any) -> bool:
    """Heuristic: is this a stdlib / site-packages module vs. a project module?"""
    import os

    # Built-in modules (no __file__)
    filepath = getattr(mod, "__file__", None)
    if filepath is None:
        # Could be built-in or namespace package — check spec
        spec = getattr(mod, "__spec__", None)
        if spec is not None:
            origin = getattr(spec, "origin", None)
            if origin == "built-in":
                return True
        return True  # No file path — treat as stdlib/builtin

    filepath = os.path.normpath(filepath)
    stdlib_paths = _get_stdlib_paths()

    # Check if the module's file is under any stdlib path
    for sp in stdlib_paths:
        if filepath.startswith(sp):
            return True

    # Check site-packages
    if "site-packages" in filepath:
        return True
    if "dist-packages" in filepath:
        return True

    # Check if it starts with a well-known stdlib name
    top_level = mod_name.split(".")[0]
    known_stdlib = {
        "abc", "argparse", "ast", "asyncio", "base64", "bisect", "builtins",
        "calendar", "cgi", "cmath", "cmd", "code", "codecs", "collections",
        "concurrent", "configparser", "contextlib", "contextvars", "copy",
        "copyreg", "cProfile", "csv", "ctypes", "curses", "dataclasses",
        "datetime", "decimal", "difflib", "dis", "distutils", "doctest",
        "email", "encodings", "enum", "errno", "faulthandler", "fcntl",
        "filecmp", "fileinput", "fnmatch", "fractions", "ftplib", "functools",
        "gc", "getopt", "getpass", "gettext", "glob", "graphlib", "gzip",
        "hashlib", "heapq", "hmac", "html", "http", "idlelib", "imaplib",
        "imghdr", "imp", "importlib", "inspect", "io", "ipaddress",
        "itertools", "json", "keyword", "lib2to3", "linecache", "locale",
        "logging", "lzma", "mailbox", "mailcap", "marshal", "math", "mimetypes",
        "mmap", "modulefinder", "multiprocessing", "netrc", "nntplib",
        "numbers", "operator", "optparse", "os", "pathlib", "pdb", "pickle",
        "pickletools", "pipes", "pkgutil", "platform", "plistlib", "poplib",
        "posix", "posixpath", "pprint", "profile", "pstats", "pty", "pwd",
        "py_compile", "pyclbr", "pydoc", "pydoc_data", "queue", "quopri",
        "random", "re", "readline", "reprlib", "resource", "rlcompleter",
        "runpy", "sched", "secrets", "select", "selectors", "shelve", "shlex",
        "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr", "socket",
        "socketserver", "sqlite3", "ssl", "stat", "statistics", "string",
        "stringprep", "struct", "subprocess", "sunau", "symtable", "sys",
        "sysconfig", "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile",
        "termios", "test", "textwrap", "threading", "time", "timeit",
        "tkinter", "token", "tokenize", "trace", "traceback", "tracemalloc",
        "tty", "turtle", "turtledemo", "types", "typing", "unicodedata",
        "unittest", "urllib", "uu", "uuid", "venv", "warnings", "wave",
        "weakref", "webbrowser", "winreg", "winsound", "wsgiref", "xdrlib",
        "xml", "xmlrpc", "zipapp", "zipfile", "zipimport", "zlib", "_thread",
    }
    if top_level in known_stdlib:
        return True

    return False


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_registered_services",
    "List all registered debug agent tools grouped by module/inspector with counts",
)
def get_registered_services() -> dict:
    import re

    # Get all tool names from the registry
    tool_names = registry.names()

    # Group by module: derive module from tool name or by inspecting the function's module
    groups: dict[str, list[str]] = {}

    for name in sorted(tool_names):
        tool = registry.get(name)
        if tool is None:
            continue

        # Derive the module from the function's __module__
        func_module = getattr(tool.func, "__module__", "unknown")
        # Simplify: take the last part of the module path
        parts = func_module.split(".")
        group_name = parts[-1] if parts else func_module

        groups.setdefault(group_name, []).append(name)

    # Build summary
    group_list = []
    for gname in sorted(groups.keys()):
        group_list.append({
            "module": gname,
            "tool_count": len(groups[gname]),
            "tools": sorted(groups[gname]),
        })

    return {
        "total_tools": len(tool_names),
        "total_modules": len(groups),
        "groups": group_list,
    }


@debug_tool(
    "get_service_dependencies",
    "Show loaded Python modules filtered to project/app modules (excludes stdlib)",
)
def get_service_dependencies(
    prefix: str = ToolParam("Filter by module name prefix (empty = all project modules)", required=False),
) -> dict:
    project_modules = []

    for name in sorted(sys.modules.keys()):
        if prefix and not name.lower().startswith(prefix.lower()):
            continue

        mod = sys.modules.get(name)
        if mod is None:
            continue
        if _is_stdlib_module(name, mod):
            continue

        project_modules.append({
            "name": name,
            "version": getattr(mod, "__version__", None),
            "file": getattr(mod, "__file__", None),
        })

    return {
        "total_project_modules": len(project_modules),
        "modules": project_modules,
    }
