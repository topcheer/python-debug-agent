"""Scheduler inspector: scheduled jobs from APScheduler, Celery beat, or custom.

Register custom scheduled jobs at runtime:

    from debug_agent.inspectors.scheduler_inspector import register_scheduled_job
    register_scheduled_job("cleanup", "every 30s")
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ─────────────────────────────────────────────────────────────

_scheduled_jobs: dict[str, dict[str, Any]] = {}


def register_scheduled_job(name: str, schedule: str, job_fn=None) -> None:
    """Register a scheduled job for introspection.

    *schedule* is a human-readable string (e.g. ``"every 30s"``, ``"*/5 * * * *"``).
    *job_fn* is optional — pass the actual callable for richer introspection.
    """
    _scheduled_jobs[name] = {
        "schedule": schedule,
        "next_run": None,
        "last_run": None,
        "last_status": None,
        "history": [],
        "job_fn": job_fn,
    }


def record_job_run(name: str, status: str, details: Any = None) -> None:
    """Record an execution for a registered job (call from the scheduler loop)."""
    job = _scheduled_jobs.get(name)
    if job is None:
        return
    now = datetime.now(timezone.utc).isoformat()
    job["last_run"] = now
    job["last_status"] = status
    job["history"].append({"timestamp": now, "status": status, "details": details})
    # Cap history to last 100 runs
    if len(job["history"]) > 100:
        job["history"] = job["history"][-100:]


def set_next_run(name: str, next_run: str | None) -> None:
    """Update the *next_run* timestamp for a registered job."""
    job = _scheduled_jobs.get(name)
    if job is not None:
        job["next_run"] = next_run


# ─── Framework auto-detection ─────────────────────────────────────────────────


def _detect_apscheduler() -> list[dict] | None:
    try:
        from apscheduler.schedulers.base import BaseScheduler  # type: ignore

        results: list[dict] = []
        for scheduler in _find_instances(BaseScheduler):
            for job in scheduler.get_jobs():  # type: ignore[attr-defined]
                results.append({
                    "name": str(job.id),
                    "schedule": str(job.trigger),
                    "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
                    "func": str(job.func),
                    "source": "APScheduler",
                })
        return results if results else None
    except Exception:
        return None


def _detect_celery_beat() -> list[dict] | None:
    try:
        from celery import Celery  # type: ignore

        results: list[dict] = []
        for app in _find_instances(Celery):
            beat = getattr(app.conf, "beat_schedule", None)
            if not beat:
                continue
            for task_name, entry in beat.items():
                results.append({
                    "name": task_name,
                    "schedule": str(entry.get("schedule", "")),
                    "task": entry.get("task", ""),
                    "source": "Celery Beat",
                })
        return results if results else None
    except Exception:
        return None


def _find_instances(base_cls: type) -> list:
    """Scan gc objects for live instances of *base_cls* (best-effort)."""
    try:
        import gc
        return [obj for obj in gc.get_objects() if isinstance(obj, base_cls)]
    except Exception:
        return []


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_scheduled_jobs",
    "List scheduled jobs from APScheduler, Celery beat, or custom registrations",
)
def get_scheduled_jobs() -> dict:
    jobs: list[dict] = []

    # Registered custom jobs
    for name, job in _scheduled_jobs.items():
        jobs.append({
            "name": name,
            "schedule": job.get("schedule"),
            "next_run": job.get("next_run"),
            "last_run": job.get("last_run"),
            "last_status": job.get("last_status"),
            "source": "custom",
        })

    # APScheduler
    aps = _detect_apscheduler()
    if aps:
        jobs.extend(aps)

    # Celery beat
    beat = _detect_celery_beat()
    if beat:
        jobs.extend(beat)

    if not jobs:
        return {
            "jobs": [],
            "count": 0,
            "message": (
                "No scheduled jobs found. Use register_scheduled_job(name, schedule) "
                "or install APScheduler / configure Celery beat."
            ),
        }

    return {"count": len(jobs), "jobs": jobs}


@debug_tool(
    "get_job_history",
    "Get execution history for a specific scheduled job",
)
def get_job_history(
    job_name: str = ToolParam("Name of the scheduled job"),
    limit: int = ToolParam("Max history entries to return", required=False),
) -> dict:
    job = _scheduled_jobs.get(job_name)
    if job is None:
        return {
            "error": f"No custom job registered for '{job_name}'",
            "note": "History is only tracked for jobs registered via register_scheduled_job().",
            "available": list(_scheduled_jobs.keys()),
        }

    history = job.get("history", [])
    if limit:
        history = history[-limit:]

    return {
        "job_name": job_name,
        "schedule": job.get("schedule"),
        "last_run": job.get("last_run"),
        "last_status": job.get("last_status"),
        "total_runs": len(job.get("history", [])),
        "history": list(reversed(history)),
    }


# ─── Convenience: execute + record a job on demand ─────────────────────────────


def run_job(name: str) -> Any:
    """Execute a registered job by name, record the outcome, and return its result."""
    job = _scheduled_jobs.get(name)
    if job is None:
        raise KeyError(f"No scheduled job registered for '{name}'")
    fn = job.get("job_fn")
    if fn is None:
        raise ValueError(f"Job '{name}' has no callable attached")
    try:
        result = fn()
        record_job_run(name, "success", details=str(result) if result is not None else None)
        return result
    except Exception:
        import traceback
        record_job_run(name, "failed", details=traceback.format_exc())
        raise


@debug_tool(
    "run_scheduled_job_now",
    "Manually trigger a registered scheduled job and record its result",
)
def run_scheduled_job_now(
    job_name: str = ToolParam("Name of the registered scheduled job to trigger"),
) -> dict:
    job = _scheduled_jobs.get(job_name)
    if job is None:
        return {
            "error": f"No scheduled job registered for '{job_name}'",
            "available": list(_scheduled_jobs.keys()),
        }
    if job.get("job_fn") is None:
        return {
            "error": f"Job '{job_name}' has no callable attached (metadata-only registration)",
        }
    try:
        result = run_job(job_name)
        return {"job_name": job_name, "status": "success", "result": str(result)}
    except Exception as exc:
        return {"job_name": job_name, "status": "failed", "error": str(exc)}
