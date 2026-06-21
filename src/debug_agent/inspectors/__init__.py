"""All built-in inspectors are auto-registered when this package is imported."""

from debug_agent.inspectors import (  # noqa: F401
    async_tasks,
    database,
    framework,
    http_tracker,
    memory,
    modules,
    runtime,
    system,
    threads,
)
