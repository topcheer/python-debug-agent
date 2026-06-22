"""Logging inspector: logger hierarchy, in-memory ring buffer, and config."""

from __future__ import annotations

import logging
from collections import deque
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── In-memory ring buffer ───────────────────────────────────────────────────

_log_buffer: deque = deque(maxlen=100)


class _BufferHandler(logging.Handler):
    """Custom handler that captures log records into the ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        _log_buffer.append(
            {
                "timestamp": record.created,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "line": record.lineno,
            }
        )


# Auto-install on root logger so all logs are captured.
_root_handler = _BufferHandler()
_root_handler.setLevel(logging.DEBUG)
logging.getLogger().addHandler(_root_handler)


# ─── Helpers ─────────────────────────────────────────────────────────────────


_LEVEL_NAMES = {
    logging.DEBUG: "DEBUG",
    logging.INFO: "INFO",
    logging.WARNING: "WARNING",
    logging.ERROR: "ERROR",
    logging.CRITICAL: "CRITICAL",
    logging.NOTSET: "NOTSET",
}


def _level_name(level: int) -> str:
    return _LEVEL_NAMES.get(level, logging.getLevelName(level))


def _describe_handler(handler: logging.Handler) -> dict[str, Any]:
    fmt = handler.formatter
    return {
        "type": type(handler).__name__,
        "level": _level_name(handler.level),
        "formatter": type(fmt).__name__ if fmt else None,
        "format": getattr(fmt, "_fmt", None) if fmt else None,
    }


def _logger_dict(logger: logging.Logger) -> dict[str, Any]:
    return {
        "name": logger.name,
        "level": _level_name(logger.level),
        "effective_level": _level_name(logger.getEffectiveLevel()),
        "propagate": logger.propagate,
        "disabled": logger.disabled,
        "parent": logger.parent.name if logger.parent else None,
        "handlers": [_describe_handler(h) for h in logger.handlers],
    }


# ─── Tools ───────────────────────────────────────────────────────────────────


@debug_tool(
    "get_logging_tree",
    "List all registered Python loggers in the logging module hierarchy (name, level, handlers, propagate, parent)",
)
def get_logging_tree() -> dict:
    manager = logging.Logger.manager
    loggers: list[dict[str, Any]] = []

    # Root logger
    root = logging.getLogger()
    loggers.append(_logger_dict(root))

    # All named loggers from the manager's dict
    for name in sorted(manager.loggerDict.keys()):
        obj = manager.loggerDict[name]
        if isinstance(obj, logging.PlaceHolder):
            # PlaceHolder is an internal node — report it but with minimal info.
            loggers.append(
                {
                    "name": name,
                    "type": "placeholder",
                    "parent": None,
                }
            )
        else:
            loggers.append(_logger_dict(obj))

    return {
        "total_loggers": len(loggers),
        "root_level": _level_name(root.level),
        "loggers": loggers,
    }


@debug_tool(
    "get_recent_logs",
    "Return recent log records from the built-in ring buffer (timestamp, level, logger, message, module, line)",
)
def get_recent_logs(
    limit: int = ToolParam("Max number of recent log entries to return", required=False),
) -> dict:
    entries = list(_log_buffer)
    total = len(entries)
    if limit:
        entries = entries[-limit:]
    # Most recent first
    entries = list(reversed(entries))
    return {"total": total, "returned": len(entries), "entries": entries}


@debug_tool(
    "get_logging_config",
    "Get logging configuration: root logger level, handler types, formatters, filters",
)
def get_logging_config() -> dict:
    root = logging.getLogger()
    handlers = []
    for handler in root.handlers:
        info = _describe_handler(handler)
        filters = []
        for flt in handler.filters:
            filters.append(
                {
                    "type": type(flt).__name__,
                    "name": getattr(flt, "name", None),
                }
            )
        info["filters"] = filters
        handlers.append(info)

    return {
        "root_level": _level_name(root.level),
        "root_handlers": handlers,
        "handler_count": len(handlers),
        "propagate": root.propagate,
        "buffer_size": len(_log_buffer),
        "buffer_capacity": _log_buffer.maxlen,
    }


@debug_tool(
    "set_log_level",
    "Dynamically set a logger's level (DEBUG/INFO/WARNING/ERROR/CRITICAL)",
)
def set_log_level(
    level: str = ToolParam("Level name: DEBUG, INFO, WARNING, ERROR, or CRITICAL"),
    logger_name: str = ToolParam("Logger name (use 'root' for the root logger)", required=False),
) -> dict:
    level_upper = level.upper().strip()
    level_map = {
        "DEBUG": logging.DEBUG,
        "INFO": logging.INFO,
        "WARNING": logging.WARNING,
        "WARN": logging.WARNING,
        "ERROR": logging.ERROR,
        "CRITICAL": logging.CRITICAL,
        "FATAL": logging.CRITICAL,
        "NOTSET": logging.NOTSET,
    }
    if level_upper not in level_map:
        return {
            "error": f"Unknown level '{level}'. Valid: {', '.join(level_map.keys())}"
        }

    resolved_name = "" if logger_name in (None, "root", "") else logger_name
    logger = logging.getLogger(resolved_name)
    old_level = logger.level
    logger.setLevel(level_map[level_upper])

    return {
        "logger": logger.name or "root",
        "old_level": _level_name(old_level),
        "new_level": level_upper,
    }
