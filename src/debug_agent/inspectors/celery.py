"""Celery inspector: registered tasks, queue stats, and worker stats.

Register a Celery app at runtime so the inspectors can reach it:

    from debug_agent.inspectors.celery import register_celery_app
    register_celery_app("default", celery_app)

All tools degrade gracefully when Celery is not installed or no app is
registered. Inspector calls (queue/worker stats) require a running broker.
"""

from __future__ import annotations

from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration mechanism ──────────────────────────────────────────────────

_registered_celery_apps: dict[str, Any] = {}


def register_celery_app(name: str, app: Any) -> None:
    """Register a Celery app under a name so the inspectors can find it."""
    _registered_celery_apps[name] = app


def _celery_available() -> bool:
    try:
        import celery  # noqa: F401
        return True
    except ImportError:
        return False


def _ensure_apps() -> dict[str, Any] | None:
    if not _celery_available():
        return None
    return _registered_celery_apps


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_celery_tasks",
    "List registered Celery tasks (name, module, bound) for each registered Celery app",
)
def get_celery_tasks() -> dict:
    apps = _ensure_apps()
    if apps is None:
        return {"error": "Celery is not installed"}

    if not apps:
        return {
            "message": "No Celery apps registered. Call register_celery_app(name, app) to register one.",
            "registered_count": 0,
        }

    result = []
    for name, app in apps.items():
        tasks: list[dict[str, Any]] = []
        try:
            task_iter = app.tasks.items()
        except Exception as exc:
            result.append({"name": name, "error": f"Could not enumerate tasks: {exc}"})
            continue

        for task_name, task in task_iter:
            # Skip Celery's own internal tasks (celery.*) unless the user cares.
            if task_name.startswith("celery."):
                continue
            tasks.append({
                "name": task_name,
                "module": getattr(getattr(task, "run", None), "__module__", None)
                or getattr(task, "__module__", None),
                "bound": bool(getattr(task, "bound", False)),
            })

        result.append({
            "name": name,
            "task_count": len(tasks),
            "tasks": tasks,
        })

    return {"registered_count": len(apps), "apps": result}


@debug_tool(
    "get_celery_queues",
    "Get Celery queue stats (active, reserved, scheduled counts per queue) via the inspector",
)
def get_celery_queues() -> dict:
    apps = _ensure_apps()
    if apps is None:
        return {"error": "Celery is not installed"}

    if not apps:
        return {
            "message": "No Celery apps registered. Call register_celery_app(name, app) to register one.",
            "registered_count": 0,
        }

    result = []
    for name, app in apps.items():
        try:
            inspect = app.control.inspect()
        except Exception as exc:
            result.append({"name": name, "error": f"Could not create inspector: {exc}"})
            continue

        active = _safe_inspect(inspect.active)
        reserved = _safe_inspect(inspect.reserved)
        scheduled = _safe_inspect(inspect.scheduled)

        per_queue: dict[str, dict[str, int]] = {}
        for payload_name, payload in (
            ("active", active),
            ("reserved", reserved),
            ("scheduled", scheduled),
        ):
            if not isinstance(payload, dict):
                continue
            for _worker, entries in payload.items():
                for entry in entries or []:
                    delivery = entry.get("delivery") if isinstance(entry, dict) else None
                    queue = None
                    if isinstance(delivery, dict):
                        queue = delivery.get("routing_key") or delivery.get("queue")
                    queue = queue or "default"
                    bucket = per_queue.setdefault(queue, {"active": 0, "reserved": 0, "scheduled": 0})
                    bucket[payload_name] += 1

        totals = {
            "active": sum(v["active"] for v in per_queue.values()),
            "reserved": sum(v["reserved"] for v in per_queue.values()),
            "scheduled": sum(v["scheduled"] for v in per_queue.values()),
        }

        result.append({
            "name": name,
            "queue_count": len(per_queue),
            "totals": totals,
            "queues": per_queue,
        })

    return {"registered_count": len(apps), "apps": result}


def _safe_inspect(func) -> Any:
    """Call a celery inspect method, returning an error dict on failure."""
    try:
        return func()
    except Exception as exc:
        return {"_error": str(exc)}


@debug_tool(
    "get_celery_workers",
    "Get Celery worker stats (active, processed, pool info) via the inspector",
)
def get_celery_workers() -> dict:
    apps = _ensure_apps()
    if apps is None:
        return {"error": "Celery is not installed"}

    if not apps:
        return {
            "message": "No Celery apps registered. Call register_celery_app(name, app) to register one.",
            "registered_count": 0,
        }

    result = []
    for name, app in apps.items():
        try:
            inspect = app.control.inspect()
        except Exception as exc:
            result.append({"name": name, "error": f"Could not create inspector: {exc}"})
            continue

        stats = _safe_inspect(inspect.stats)
        active = _safe_inspect(inspect.active)
        ping = _safe_inspect(inspect.ping)

        workers: list[dict[str, Any]] = []
        if isinstance(stats, dict):
            for worker_name, worker_stats in stats.items():
                pool = worker_stats.get("pool", {}) if isinstance(worker_stats, dict) else {}
                broker = worker_stats.get("broker", {}) if isinstance(worker_stats, dict) else {}
                rusage = worker_stats.get("rusage", {}) if isinstance(worker_stats, dict) else {}
                active_list = active.get(worker_name, []) if isinstance(active, dict) else []
                total_processed = 0
                if isinstance(worker_stats, dict):
                    total_processed = sum(
                        int(v) for v in (worker_stats.get("total", {}) or {}).values()
                    )
                workers.append({
                    "worker": worker_name,
                    "active_count": len(active_list) if isinstance(active_list, list) else 0,
                    "processed_total": total_processed,
                    "pool": {
                        "implementation": pool.get("implementation") if isinstance(pool, dict) else None,
                        "max_concurrency": pool.get("max-concurrency") if isinstance(pool, dict) else None,
                        "processes": pool.get("processes") if isinstance(pool, dict) else None,
                    },
                    "broker": {
                        "transport": broker.get("transport") if isinstance(broker, dict) else None,
                        "name": broker.get("name") if isinstance(broker, dict) else None,
                    },
                    "uptime": worker_stats.get("uptime") if isinstance(worker_stats, dict) else None,
                    "rusage": _summarise_rusage(rusage),
                })

        reachable = list(ping.keys()) if isinstance(ping, dict) else []

        result.append({
            "name": name,
            "worker_count": len(workers),
            "reachable_workers": reachable,
            "workers": workers,
        })

    return {"registered_count": len(apps), "apps": result}


def _summarise_rusage(rusage: Any) -> dict[str, Any]:
    if not isinstance(rusage, dict):
        return {}
    keys = ("utime", "stime", "maxrss", "idrss", "isrss", "ixrss", "minflt", "majflt", "nvcsw", "nivcsw")
    return {k: rusage.get(k) for k in keys if k in rusage}
