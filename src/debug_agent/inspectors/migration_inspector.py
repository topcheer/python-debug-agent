"""Migration inspector: database schema migration status and history.

Register a migration provider for custom tracking:

    from debug_agent.inspectors.migration_inspector import register_migration_provider

    @register_migration_provider
    def my_provider():
        return {
            "current_version": "0003",
            "pending": ["0004_add_index"],
            "history": [{"version": "0003", "applied_at": "2024-01-15T10:00:00Z"}],
            "source": "custom",
        }

Auto-detects Alembic (``alembic.config``) and Django
(``django.db.migrations.recorder.MigrationRecorder``).
"""

from __future__ import annotations

from typing import Any, Callable

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── Registration ──────────────────────────────────────────────────────────────

_migration_provider: Callable[..., dict[str, Any]] | None = None


def register_migration_provider(fn: Callable[..., dict[str, Any]]) -> Callable[..., dict[str, Any]]:
    """Register (or use as a decorator) a function that returns migration info.

    The callable should return a dict with any of these keys:
        current_version: str
        pending:        list[str | dict]
        history:        list[dict]  (version, applied_at, ...)
        source:         str
    """
    global _migration_provider
    _migration_provider = fn
    return fn


# ─── Auto-detection helpers ───────────────────────────────────────────────────


def _detect_alembic() -> dict[str, Any] | None:
    """Best-effort Alembic version / pending / history discovery."""
    try:
        from alembic.config import Config  # type: ignore
        from alembic.script import ScriptDirectory  # type: ignore
    except ImportError:
        return None

    try:
        import os
        ini_path = os.environ.get("ALEMBIC_CONFIG", "alembic.ini")
        if not os.path.isfile(ini_path):
            return None

        cfg = Config(ini_path)
        script_dir = ScriptDirectory.from_config(cfg)

        heads = script_dir.get_heads()
        revisions = list(script_dir.walk_revisions())
        revision_list = [
            {
                "revision": rev.revision,
                "down_revision": rev.down_revision,
                "description": rev.doc,
            }
            for rev in revisions
        ]

        return {
            "source": "alembic",
            "current_version": heads[0] if heads else None,
            "heads": heads,
            "pending": [],  # pending requires DB introspection; see below
            "history": revision_list,
            "total_revisions": len(revision_list),
        }
    except Exception:
        return None


def _detect_alembic_pending() -> list[str]:
    """Return unapplied Alembic revisions by querying the DB version table."""
    try:
        from alembic.config import Config  # type: ignore
        from alembic.script import ScriptDirectory  # type: ignore
        from alembic.runtime.migration import MigrationContext  # type: ignore
        from sqlalchemy import create_engine  # type: ignore
        import os
        import re
    except ImportError:
        return []

    try:
        ini_path = os.environ.get("ALEMBIC_CONFIG", "alembic.ini")
        if not os.path.isfile(ini_path):
            return []

        cfg = Config(ini_path)
        script_dir = ScriptDirectory.from_config(cfg)

        # Extract the SQLAlchemy URL from the alembic config
        sql_url = cfg.get_main_option("sqlalchemy.url")
        if not sql_url:
            return []

        engine = create_engine(sql_url)
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)
            current_rev = ctx.get_current_revision()

        if current_rev is None:
            return [rev.revision for rev in script_dir.walk_revisions()]

        return [
            rev.revision
            for rev in script_dir.walk_revisions()
            if rev.revision != current_rev
        ]
    except Exception:
        return []


def _detect_django() -> dict[str, Any] | None:
    """Best-effort Django migration state discovery."""
    try:
        from django.db.migrations.recorder import MigrationRecorder  # type: ignore
        from django.db import connections, DEFAULT_DB_ALIAS  # type: ignore
    except ImportError:
        return None

    try:
        connection = connections[DEFAULT_DB_ALIAS]
        recorder = MigrationRecorder(connection)

        applied = recorder.applied_migrations()  # dict: (app, name) -> Migration
        history = [
            {
                "app": app,
                "name": name,
                "applied_at": (
                    applied[(app, name)].applied.isoformat()
                    if hasattr(applied[(app, name)], "applied") and applied[(app, name)].applied
                    else None
                ),
            }
            for app, name in sorted(applied.keys())
        ]

        return {
            "source": "django",
            "current_version": None,
            "applied_count": len(applied),
            "history": history,
            "pending": [],
        }
    except Exception:
        return None


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "get_migration_status",
    "Get current schema version from Alembic, Django, or a registered migration provider",
)
def get_migration_status() -> dict:
    if _migration_provider is not None:
        try:
            data = _migration_provider()
            return {
                "source": data.get("source", "custom"),
                "current_version": data.get("current_version"),
                "applied_count": len(data.get("history", [])),
                "pending_count": len(data.get("pending", [])),
            }
        except Exception as exc:
            return {"error": f"Migration provider raised: {exc}"}

    # Alembic
    alembic = _detect_alembic()
    if alembic is not None:
        pending = _detect_alembic_pending()
        alembic["pending"] = pending
        return {
            "source": "alembic",
            "current_version": alembic["current_version"],
            "heads": alembic.get("heads", []),
            "applied_count": alembic.get("total_revisions", 0) - len(pending),
            "pending_count": len(pending),
        }

    # Django
    django = _detect_django()
    if django is not None:
        return {
            "source": "django",
            "current_version": None,
            "applied_count": django["applied_count"],
            "pending_count": 0,
        }

    return {
        "source": None,
        "message": (
            "No migration framework detected. Install Alembic/Django or "
            "register a provider via register_migration_provider(fn)."
        ),
    }


@debug_tool(
    "get_pending_migrations",
    "List unapplied database migrations",
)
def get_pending_migrations() -> dict:
    if _migration_provider is not None:
        try:
            data = _migration_provider()
            pending = data.get("pending", [])
            return {
                "source": data.get("source", "custom"),
                "count": len(pending),
                "pending": pending,
            }
        except Exception as exc:
            return {"error": f"Migration provider raised: {exc}"}

    alembic = _detect_alembic()
    if alembic is not None:
        pending = _detect_alembic_pending()
        return {
            "source": "alembic",
            "count": len(pending),
            "pending": pending,
            "current_version": alembic.get("current_version"),
        }

    django = _detect_django()
    if django is not None:
        return {
            "source": "django",
            "count": len(django.get("pending", [])),
            "pending": django.get("pending", []),
        }

    return {
        "source": None,
        "count": 0,
        "pending": [],
        "message": "No migration framework detected.",
    }


@debug_tool(
    "get_migration_history",
    "Get applied migration log with timestamps",
)
def get_migration_history(
    limit: int | None = None,
) -> dict:
    effective_limit = limit if isinstance(limit, int) else 0
    if _migration_provider is not None:
        try:
            data = _migration_provider()
            history = list(data.get("history", []))
            if effective_limit:
                history = history[:effective_limit]
            return {
                "source": data.get("source", "custom"),
                "count": len(history),
                "history": history,
            }
        except Exception as exc:
            return {"error": f"Migration provider raised: {exc}"}

    alembic = _detect_alembic()
    if alembic is not None:
        history = alembic.get("history", [])
        if effective_limit:
            history = history[:effective_limit]
        return {
            "source": "alembic",
            "count": len(history),
            "history": history,
        }

    django = _detect_django()
    if django is not None:
        history = django.get("history", [])
        if effective_limit:
            history = history[:effective_limit]
        return {
            "source": "django",
            "count": len(history),
            "history": history,
        }

    return {
        "source": None,
        "count": 0,
        "history": [],
        "message": "No migration framework detected.",
    }
