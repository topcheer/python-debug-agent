"""Database inspector: SQLAlchemy engines, connection pools."""

from __future__ import annotations

import sys
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


def _find_sqlalchemy_engines() -> list:
    """Find SQLAlchemy Engine instances in loaded modules."""
    engines = []
    seen_ids = set()

    # Try to find via SQLAlchemy's own registries first
    try:
        from sqlalchemy import inspect as sa_inspect
        from sqlalchemy.engine import Engine
    except ImportError:
        return engines

    for mod in list(sys.modules.values()):
        if mod is None or mod.__name__.startswith("debug_agent"):
            continue
        for attr_name in dir(mod):
            if attr_name.startswith("_"):
                continue
            try:
                obj = getattr(mod, attr_name)
                if isinstance(obj, Engine) and id(obj) not in seen_ids:
                    seen_ids.add(id(obj))
                    engines.append(obj)
            except Exception:
                continue

    return engines


@debug_tool(
    "get_sqlalchemy_engines",
    "Find SQLAlchemy engines and their connection pool status",
)
def get_sqlalchemy_engines() -> dict:
    try:
        from sqlalchemy import create_engine, inspect as sa_inspect
        from sqlalchemy.pool import QueuePool, NullPool, StaticPool
    except ImportError:
        return {"error": "SQLAlchemy is not installed"}

    engines = _find_sqlalchemy_engines()
    if not engines:
        return {"message": "No SQLAlchemy engines found in loaded modules"}

    result = []
    for engine in engines:
        pool = engine.pool
        pool_info: dict = {
            "pool_type": type(pool).__name__,
        }

        if isinstance(pool, QueuePool):
            pool_info["size"] = pool.size()
            pool_info["checked_in"] = pool.checkedin()
            pool_info["checked_out"] = pool.checkedout()
            pool_info["overflow"] = pool.overflow()
            pool_info["checked_out_total"] = pool.status()

        url = str(engine.url)
        # Mask password in URL
        if "" in url:
            parts = url.split("@")
            if len(parts) >= 2:
                cred = parts[0].split(":")
                if len(cred) >= 3:
                    cred[-1] = "***"
                    parts[0] = ":".join(cred)
                    url = "@".join(parts)

        result.append({
            "url": url,
            "dialect": engine.dialect.name,
            "driver": engine.driver,
            "pool": pool_info,
        })

    return {"engine_count": len(result), "engines": result}


@debug_tool(
    "get_db_connections",
    "Inspect database connection pools and active connections if available",
)
def get_db_connections() -> dict:
    try:
        from sqlalchemy.pool import QueuePool, SingletonThreadPool, StaticPool
    except ImportError:
        return {"error": "SQLAlchemy is not installed"}

    engines = _find_sqlalchemy_engines()
    if not engines:
        return {"message": "No SQLAlchemy engines found"}

    connections = []
    for engine in engines:
        pool = engine.pool
        info: dict = {
            "dialect": engine.dialect.name,
            "pool_type": type(pool).__name__,
        }

        if hasattr(pool, "size"):
            info["pool_size"] = pool.size()
        if hasattr(pool, "checkedin"):
            info["checked_in"] = pool.checkedin()
        if hasattr(pool, "checkedout"):
            info["checked_out"] = pool.checkedout()
        if hasattr(pool, "overflow"):
            info["overflow"] = pool.overflow()

        # Try to get pool status string
        try:
            info["pool_status"] = pool.status()
        except Exception:
            pass

        connections.append(info)

    return {"total_engines": len(connections), "connection_pools": connections}
