"""All built-in inspectors are auto-registered when this package is imported."""

from debug_agent.inspectors import (  # noqa: F401
    async_tasks,
    celery,
    database,
    django,
    flask_ext,
    framework,
    http_tracker,
    jinja2,
    memory,
    modules,
    redis,
    runtime,
    signals,
    system,
    threads,
)
