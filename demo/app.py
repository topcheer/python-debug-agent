"""Demo: Order Management API with Debug Agent integrated.

Stack:
  - Flask            web framework
  - SQLAlchemy       database storage (SQLite by default)
  - redis-py         caching layer
  - Celery           background task processing (same Redis as broker)

Run:
    docker compose up -d redis        # start Redis on :6379
    pip install -e ".[flask,redis,celery,dev]"
    LLM_API_KEY=your-key python demo/app.py

    # Optional: start a Celery worker in another terminal
    celery -A demo.celery_app worker --loglevel=info

Then open http://localhost:8000/agent
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

from flask import Flask, jsonify, request, abort

from debug_agent.middleware import create_flask_blueprint
from debug_agent.inspectors.http_tracker import record_request

# ─── Configuration ───────────────────────────────────────────────────────────

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///demo_orders.db")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("order_api")

# ─── SQLAlchemy ──────────────────────────────────────────────────────────────

try:
    from flask_sqlalchemy import SQLAlchemy  # type: ignore
    _HAS_FLASK_SQLALCHEMY = True
except ImportError:  # pragma: no cover - optional dependency
    SQLAlchemy = None  # type: ignore
    _HAS_FLASK_SQLALCHEMY = False

try:
    from sqlalchemy import (
        Column,
        Float,
        Integer,
        String,
        DateTime,
        create_engine,
    )
    from sqlalchemy.orm import declarative_base, sessionmaker
    _HAS_SQLALCHEMY = True
except ImportError:  # pragma: no cover - optional dependency
    _HAS_SQLALCHEMY = False

# ─── Redis ───────────────────────────────────────────────────────────────────

try:
    import redis  # type: ignore
    redis_client = redis.Redis.from_url(REDIS_URL, decode_responses=True)
    _HAS_REDIS = True
except ImportError:  # pragma: no cover - optional dependency
    redis_client = None
    _HAS_REDIS = False

# ─── Celery ──────────────────────────────────────────────────────────────────

try:
    from celery import Celery  # type: ignore
    celery_app = Celery(
        "demo",
        broker=REDIS_URL,
        backend=REDIS_URL,
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
    _HAS_CELERY = True
except ImportError:  # pragma: no cover - optional dependency
    celery_app = None  # type: ignore
    _HAS_CELERY = False

# ─── Flask app ───────────────────────────────────────────────────────────────

app = Flask(__name__)
app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["REDIS_URL"] = REDIS_URL

# SQLAlchemy storage (prefer the Flask-SQLAlchemy extension; fall back to a
# bare engine/session so the demo runs even without the extension installed).
if _HAS_FLASK_SQLALCHEMY:
    db = SQLAlchemy(app)

    class Order(db.Model):  # type: ignore[misc, valid-type]
        __tablename__ = "orders"
        id = db.Column(db.Integer, primary_key=True)
        customer = db.Column(db.String(200), nullable=False)
        item = db.Column(db.String(200), nullable=False)
        quantity = db.Column(db.Integer, nullable=False, default=1)
        price = db.Column(db.Float, nullable=False, default=0.0)
        total = db.Column(db.Float, nullable=False, default=0.0)
        status = db.Column(db.String(50), nullable=False, default="pending")
        created_at = db.Column(
            db.DateTime,
            nullable=False,
            default=lambda: datetime.now(timezone.utc),
        )

    with app.app_context():
        db.create_all()

elif _HAS_SQLALCHEMY:
    Base = declarative_base()

    class Order(Base):  # type: ignore[misc, valid-type]
        __tablename__ = "orders"
        id = Column(Integer, primary_key=True)
        customer = Column(String(200), nullable=False)
        item = Column(String(200), nullable=False)
        quantity = Column(Integer, nullable=False, default=1)
        price = Column(Float, nullable=False, default=0.0)
        total = Column(Float, nullable=False, default=0.0)
        status = Column(String(50), nullable=False, default="pending")
        created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))

        def to_dict(self) -> dict:
            return {
                "id": self.id,
                "customer": self.customer,
                "item": self.item,
                "quantity": self.quantity,
                "price": self.price,
                "total": self.total,
                "status": self.status,
                "created_at": self.created_at.isoformat() if self.created_at else None,
            }

    engine = create_engine(DATABASE_URL, future=True)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    Base.metadata.create_all(engine)
else:  # pragma: no cover - both optional deps missing
    Order = None  # type: ignore


def _seed_orders() -> None:
    """Seed a few sample orders on first run (no-op if data exists)."""
    seeds = [
        {"customer": "Alice Wang", "item": "MacBook Pro 16\"", "quantity": 1, "price": 2499.00},
        {"customer": "Bob Zhang", "item": "Logitech MX Master 3S", "quantity": 3, "price": 99.99},
        {"customer": "Charlie Li", "item": "Dell UltraSharp 32\" 4K", "quantity": 2, "price": 899.50},
    ]
    if _HAS_FLASK_SQLALCHEMY:
        if Order.query.count() == 0:
            for s in seeds:
                order = Order(
                    customer=s["customer"],
                    item=s["item"],
                    quantity=s["quantity"],
                    price=s["price"],
                    total=round(s["quantity"] * s["price"], 2),
                    status="confirmed",
                )
                db.session.add(order)
            db.session.commit()
            logger.info("Seeded %d sample orders (flask_sqlalchemy)", len(seeds))
    elif _HAS_SQLALCHEMY:
        with SessionLocal() as session:
            if session.query(Order).count() == 0:
                for s in seeds:
                    order = Order(
                        customer=s["customer"],
                        item=s["item"],
                        quantity=s["quantity"],
                        price=s["price"],
                        total=round(s["quantity"] * s["price"], 2),
                        status="confirmed",
                    )
                    session.add(order)
                session.commit()
                logger.info("Seeded %d sample orders (sqlalchemy)", len(seeds))


# Seed sample orders for whichever storage backend is available. The Flask
# extension path needs an app context for the session/query to work.
if _HAS_FLASK_SQLALCHEMY:
    with app.app_context():
        _seed_orders()
elif _HAS_SQLALCHEMY:
    _seed_orders()

# ─── Redis cache helpers ─────────────────────────────────────────────────────

_CACHE_TTL = 30  # seconds


def _cache_get(key: str):
    if not _HAS_REDIS:
        return None
    try:
        return redis_client.get(key)
    except Exception as exc:
        logger.warning("Redis GET failed for %s: %s", key, exc)
        return None


def _cache_set_json(key: str, value: str) -> None:
    if not _HAS_REDIS:
        return
    try:
        redis_client.setex(key, _CACHE_TTL, value)
    except Exception as exc:
        logger.warning("Redis SET failed for %s: %s", key, exc)


def _cache_delete(*keys: str) -> None:
    if not _HAS_REDIS:
        return
    try:
        redis_client.delete(*keys)
    except Exception as exc:
        logger.warning("Redis DELETE failed for %s: %s", keys, exc)


# ─── Celery background task ──────────────────────────────────────────────────


if _HAS_CELERY:

    @celery_app.task(name="demo.process_order", bind=True)
    def process_order(self, order_id: int) -> dict:  # noqa: D401
        """Background task: mark an order as processed.

        Runs in the Celery worker process. We use the Flask app context so
        SQLAlchemy sessions work the same as in the web request path.
        """
        with app.app_context():
            if _HAS_FLASK_SQLALCHEMY:
                order = db.session.get(Order, order_id)
            elif _HAS_SQLALCHEMY:
                with SessionLocal() as session:
                    order = session.get(Order, order_id)
            else:
                return {"order_id": order_id, "status": "skipped"}

            if order is None:
                return {"order_id": order_id, "status": "not_found"}

            order.status = "processed"
            if _HAS_FLASK_SQLALCHEMY:
                db.session.commit()
            elif _HAS_SQLALCHEMY:
                session.commit()

            _cache_delete(f"order:{order_id}", "orders:list")
            logger.info("Celery processed order #%s", order_id)
            return {"order_id": order_id, "status": "processed"}


def _enqueue_process_order(order_id: int) -> dict:
    """Queue the background processing task (or run synchronously if Celery is absent).

    If Celery is installed but the broker is unreachable, we fall back to
    processing the order inline so the demo keeps working without a running
    Redis/worker.
    """
    if _HAS_CELERY and _broker_reachable():
        try:
            async_result = process_order.apply_async(args=[order_id])
            return {"queued": True, "task_id": async_result.id}
        except Exception as exc:
            logger.warning(
                "Celery apply_async failed (%s); processing order #%d inline",
                type(exc).__name__, order_id,
            )
    # Fallback: process inline (Celery absent OR broker down).
    return _process_order_inline(order_id)


def _broker_reachable() -> bool:
    """Quick, non-blocking-ish check that the Redis broker responds to PING."""
    if not _HAS_REDIS:
        return False
    try:
        redis_client.ping()
        return True
    except Exception:
        return False


def _process_order_inline(order_id: int) -> dict:
    """Mark an order as processed synchronously (no Celery worker required)."""
    if _HAS_FLASK_SQLALCHEMY:
        order = db.session.get(Order, order_id)
        if order is None:
            return {"queued": False, "status": "not_found"}
        order.status = "processed"
        db.session.commit()
        _cache_delete(f"order:{order_id}", "orders:list")
        return {"queued": False, "processed_inline": True, "status": "processed"}
    if _HAS_SQLALCHEMY:
        with SessionLocal() as session:
            order = session.get(Order, order_id)
            if order is None:
                return {"queued": False, "status": "not_found"}
            order.status = "processed"
            session.commit()
        _cache_delete(f"order:{order_id}", "orders:list")
        return {"queued": False, "processed_inline": True, "status": "processed"}
    return {"queued": False}


# ─── Debug Agent integration ─────────────────────────────────────────────────

app.register_blueprint(create_flask_blueprint())

# Register Redis / Celery with the debug agent inspectors so they can be
# introspected at runtime. These imports are safe even when the deps are
# missing — the registration functions are always available.
from debug_agent.inspectors.redis import register_redis_client  # noqa: E402
from debug_agent.inspectors.celery import register_celery_app  # noqa: E402

if _HAS_REDIS:
    register_redis_client("default", redis_client)
if _HAS_CELERY:
    register_celery_app("default", celery_app)

# ─── v0.5.0 Inspector integrations ───────────────────────────────────────────

from debug_agent.inspectors.security_inspector import (  # noqa: E402
    register_auth_config,
    register_session_store,
)
from debug_agent.inspectors.health_inspector import register_health_check  # noqa: E402
from debug_agent.inspectors.scheduler_inspector import (  # noqa: E402
    register_scheduled_job,
    record_job_run,
    set_next_run,
)
from debug_agent.inspectors.error_tracking import (  # noqa: E402
    install_flask_error_handler,
    capture_error,
)
from debug_agent.inspectors.websocket_inspector import register_ws_server  # noqa: E402

# v0.6.0 inspectors
from debug_agent.inspectors.locks_inspector import register_lock  # noqa: E402
from debug_agent.inspectors.config_inspector import register_config  # noqa: E402
from debug_agent.inspectors.feature_flag_inspector import register_feature_flag  # noqa: E402
from debug_agent.inspectors.migration_inspector import register_migration_provider  # noqa: E402
from debug_agent.inspectors.pool_inspector import register_pool  # noqa: E402

from functools import wraps  # noqa: E402
import threading  # noqa: E402

# ─── Security: API Key auth ───────────────────────────────────────────────────

API_KEY = os.environ.get("API_KEY", "demo-secret-key-12345")
ACTIVE_SESSIONS: dict[str, dict] = {}


def _check_api_key() -> bool:
    """Return True if the X-API-Key header matches."""
    provided = request.headers.get("X-API-Key", "")
    return provided == API_KEY


def require_api_key(fn):
    """Decorator: enforce X-API-Key header on a route."""
    @wraps(fn)
    def _wrapper(*args, **kwargs):
        if not _check_api_key():
            abort(401, "Missing or invalid X-API-Key header")
        return fn(*args, **kwargs)
    return _wrapper


# Register the auth configuration with the security inspector
register_auth_config("api_key", {
    "scheme": "api_key",
    "header_name": "X-API-Key",
    "secret_key": API_KEY,
    "token_expiry": None,
    "protected_paths": ["/api/orders"],
})

# Register a simple in-memory session store for demo purposes
register_session_store("demo_sessions", ACTIVE_SESSIONS)


@app.before_request
def _enforce_api_key():
    """Enforce X-API-Key on all /api/orders routes."""
    if request.path.startswith("/api/orders"):
        if not _check_api_key():
            abort(401, "Missing or invalid X-API-Key header. Set the X-API-Key header.")


# ─── v0.6.0 Inspector integrations ───────────────────────────────────────────

# Lock: protect the order counter
_order_lock = threading.Lock()
register_lock("order_counter", _order_lock)

# Config: register Flask config values (passwords are auto-masked)
register_config(
    "flask",
    {
        "DEBUG": app.config.get("DEBUG", True),
        "TESTING": app.config.get("TESTING", False),
        "SQLALCHEMY_DATABASE_URI": DATABASE_URL,
        "REDIS_URL": REDIS_URL,
    },
    sources={
        "SQLALCHEMY_DATABASE_URI": "env" if os.environ.get("DATABASE_URL") else "default",
        "REDIS_URL": "env" if os.environ.get("REDIS_URL") else "default",
        "DEBUG": "default",
        "TESTING": "default",
    },
)

# Feature flags
register_feature_flag("new_ui", enabled=True)
register_feature_flag("experimental_cache", enabled=False)
register_feature_flag("ai_search", enabled=True, variant="v2")

# Migration: simple schema-version tracking
_SCHEMA_VERSION = 3
_APPLIED_MIGRATIONS = [
    {"version": "0001", "name": "initial", "applied_at": "2024-01-10T09:00:00Z"},
    {"version": "0002", "name": "add_quantity_index", "applied_at": "2024-01-12T14:30:00Z"},
    {"version": "0003", "name": "add_status_column", "applied_at": "2024-01-15T10:00:00Z"},
]
_ALL_MIGRATIONS = _APPLIED_MIGRATIONS + [
    {"version": "0004", "name": "add_soft_delete", "applied_at": None},
]


def _migration_info():
    applied_versions = {m["version"] for m in _APPLIED_MIGRATIONS}
    pending = [m for m in _ALL_MIGRATIONS if m["version"] not in applied_versions]
    return {
        "source": "custom",
        "current_version": _APPLIED_MIGRATIONS[-1]["version"],
        "pending": pending,
        "history": list(_APPLIED_MIGRATIONS),
    }


register_migration_provider(_migration_info)

# Pool: register the SQLAlchemy engine pool
if _HAS_FLASK_SQLALCHEMY:
    try:
        register_pool("flask_sqlalchemy", db.engine.pool)
    except Exception:
        pass
elif _HAS_SQLALCHEMY:
    try:
        register_pool("sqlalchemy_default", engine.pool)
    except Exception:
        pass

# ─── Health checks ────────────────────────────────────────────────────────────


@register_health_check("database")
def _health_database():
    """Check database connectivity via SELECT 1."""
    try:
        if _HAS_FLASK_SQLALCHEMY:
            db.session.execute(db.text("SELECT 1"))
            return {"status": "UP", "details": {"engine": "flask_sqlalchemy"}}
        elif _HAS_SQLALCHEMY:
            with SessionLocal() as session:
                session.execute(__import__("sqlalchemy").text("SELECT 1"))
            return {"status": "UP", "details": {"engine": "sqlalchemy"}}
        else:
            return {"status": "DEGRADED", "details": {"message": "No database configured"}}
    except Exception as exc:
        return {"status": "DOWN", "details": {"error": str(exc)}}


@register_health_check("redis")
def _health_redis():
    """Check Redis connectivity via PING."""
    if not _HAS_REDIS:
        return {"status": "DEGRADED", "details": {"message": "Redis not installed"}}
    try:
        redis_client.ping()
        return {"status": "UP", "details": {"url": REDIS_URL}}
    except Exception as exc:
        return {"status": "DOWN", "details": {"error": str(exc)}}


@register_health_check("disk")
def _health_disk():
    """Check available disk space."""
    import shutil
    total, used, free = shutil.disk_usage(".")
    free_pct = free / total * 100 if total else 0
    if free_pct < 5:
        status = "DOWN"
    elif free_pct < 20:
        status = "DEGRADED"
    else:
        status = "UP"
    return {
        "status": status,
        "details": {
            "free_gb": round(free / 1024**3, 2),
            "total_gb": round(total / 1024**3, 2),
            "free_pct": round(free_pct, 1),
        },
    }


# ─── Scheduled job: periodic cleanup every 30s ────────────────────────────────


def _cleanup_expired_caches():
    """Simulated cleanup job — deletes stale Redis cache keys."""
    cleaned = 0
    if _HAS_REDIS:
        try:
            for key in redis_client.scan_iter("temp:*"):
                redis_client.delete(key)
                cleaned += 1
        except Exception:
            pass
    logger.info("Cleanup job ran — removed %d stale keys", cleaned)
    return {"cleaned": cleaned}


register_scheduled_job("cleanup", "every 30s", job_fn=_cleanup_expired_caches)

_scheduler_timer = None


def _run_cleanup_loop():
    """Background thread that fires the cleanup job every 30 seconds."""
    global _scheduler_timer
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    next_ts = (_dt.now(_tz.utc) + _td(seconds=30)).isoformat()
    set_next_run("cleanup", next_ts)
    try:
        result = _cleanup_expired_caches()
        record_job_run("cleanup", "success", details=result)
    except Exception as exc:
        record_job_run("cleanup", "failed", details=str(exc))
    _scheduler_timer = threading.Timer(30.0, _run_cleanup_loop)
    _scheduler_timer.daemon = True
    _scheduler_timer.start()


# ─── Error tracking ───────────────────────────────────────────────────────────

# Install Flask error handler that captures exceptions into the ring buffer
install_flask_error_handler(app)


# ─── WebSocket (flask-sock) ───────────────────────────────────────────────────

try:
    from flask_sock import Sock  # type: ignore
    _ws = Sock(app)
    _HAS_FLASK_SOCK = True
except ImportError:  # pragma: no cover - optional dependency
    _ws = None
    _HAS_FLASK_SOCK = False


if _HAS_FLASK_SOCK:
    register_ws_server("flask_sock", _ws)

    @_ws.route("/ws")
    def _ws_echo(ws):
        """Simple WebSocket echo endpoint."""
        while True:
            data = ws.receive()
            if data is None:
                break
            ws.send(f"echo: {data}")


# ─── Request tracking middleware ─────────────────────────────────────────────


@app.before_request
def _before():
    request._start_time = time.time()


@app.after_request
def _after(response):
    duration_ms = (time.time() - getattr(request, "_start_time", time.time())) * 1000
    client = request.remote_addr or ""
    record_request(request.method, request.path, response.status_code, duration_ms, client)
    return response


# ─── Error handlers ──────────────────────────────────────────────────────────


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "message": str(e.description)}), 404


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "message": str(e.description)}), 400


@app.errorhandler(500)
def internal_error(e):
    logger.error("Internal server error: %s", e)
    message = e.description if hasattr(e, "description") else str(e)
    return jsonify({"error": "Internal server error", "message": message}), 500


# ─── Order CRUD endpoints ────────────────────────────────────────────────────


@app.route("/api/orders", methods=["GET"])
def list_orders():
    cached = _cache_get("orders:list")
    if cached:
        import json
        logger.info("Returning cached order list (Redis)")
        orders = json.loads(cached)
        return jsonify({"orders": orders, "count": len(orders), "cached": True})

    orders = _query_all_orders()
    import json
    _cache_set_json("orders:list", json.dumps(orders))
    logger.info("Listing %d orders", len(orders))
    return jsonify({"orders": orders, "count": len(orders), "cached": False})


@app.route("/api/orders", methods=["POST"])
def create_order():
    data = request.get_json(silent=True)
    if not data:
        abort(400, "Request body must be JSON")

    required = ["customer", "item", "quantity", "price"]
    for field in required:
        if field not in data:
            abort(400, f"Missing required field: {field}")

    order = _create_order(
        customer=data["customer"],
        item=data["item"],
        quantity=int(data["quantity"]),
        price=float(data["price"]),
    )

    # Queue background processing (mark as "processed").
    task_info = _enqueue_process_order(order["id"])

    logger.info(
        "Created order #%d for %s — %s x%d (task=%s)",
        order["id"], order["customer"], order["item"], order["quantity"], task_info,
    )
    return jsonify({**order, "task": task_info}), 201


@app.route("/api/orders/<int:oid>", methods=["GET"])
def get_order(oid: int):
    cache_key = f"order:{oid}"
    cached = _cache_get(cache_key)
    if cached:
        import json
        logger.info("Returning cached order #%d (Redis)", oid)
        return jsonify(json.loads(cached))

    order = _query_order(oid)
    if order is None:
        abort(404, f"Order {oid} not found")

    import json
    _cache_set_json(cache_key, json.dumps(order))
    logger.info("Retrieved order #%d", oid)
    return jsonify(order)


@app.route("/api/orders/<int:oid>", methods=["PUT"])
def update_order(oid: int):
    data = request.get_json(silent=True)
    if not data:
        abort(400, "Request body must be JSON")

    order = _query_order(oid)
    if order is None:
        abort(404, f"Order {oid} not found")

    updated = _update_order(oid, data)
    _cache_delete(f"order:{oid}", "orders:list")
    logger.info("Updated order #%d — status=%s", oid, updated.get("status"))
    return jsonify(updated)


@app.route("/api/orders/<int:oid>", methods=["DELETE"])
def delete_order(oid: int):
    deleted = _delete_order(oid)
    if deleted is None:
        abort(404, f"Order {oid} not found")

    _cache_delete(f"order:{oid}", "orders:list")
    logger.info("Deleted order #%d", oid)
    return jsonify({"deleted": oid, "customer": deleted["customer"]})


# ─── Storage helpers (abstract Flask-SQLAlchemy vs bare SQLAlchemy) ───────────


def _serialize(order) -> dict:
    return {
        "id": order.id,
        "customer": order.customer,
        "item": order.item,
        "quantity": order.quantity,
        "price": order.price,
        "total": order.total,
        "status": order.status,
        "created_at": order.created_at.isoformat() if order.created_at else None,
    }


def _query_all_orders() -> list[dict]:
    if _HAS_FLASK_SQLALCHEMY:
        return [_serialize(o) for o in Order.query.order_by(Order.id).all()]
    if _HAS_SQLALCHEMY:
        with SessionLocal() as session:
            return [_serialize(o) for o in session.query(Order).order_by(Order.id).all()]
    return []


def _query_order(oid: int) -> dict | None:
    if _HAS_FLASK_SQLALCHEMY:
        order = db.session.get(Order, oid)
        return _serialize(order) if order else None
    if _HAS_SQLALCHEMY:
        with SessionLocal() as session:
            order = session.get(Order, oid)
            return _serialize(order) if order else None
    return None


def _create_order(customer: str, item: str, quantity: int, price: float) -> dict:
    total = round(quantity * price, 2)
    if _HAS_FLASK_SQLALCHEMY:
        with _order_lock:
            order = Order(
                customer=customer,
                item=item,
                quantity=quantity,
                price=price,
                total=total,
                status="pending",
            )
            db.session.add(order)
            db.session.commit()
            return _serialize(order)
    if _HAS_SQLALCHEMY:
        with _order_lock:
            with SessionLocal() as session:
                order = Order(
                    customer=customer,
                    item=item,
                    quantity=quantity,
                    price=price,
                    total=total,
                    status="pending",
                )
                session.add(order)
                session.commit()
                session.refresh(order)
                return _serialize(order)
    return {}


def _update_order(oid: int, data: dict) -> dict | None:
    if _HAS_FLASK_SQLALCHEMY:
        order = db.session.get(Order, oid)
        if order is None:
            return None
        for field in ["customer", "item", "quantity", "price", "status"]:
            if field in data:
                setattr(order, field, data[field])
        order.total = round(int(order.quantity) * float(order.price), 2)
        db.session.commit()
        return _serialize(order)
    if _HAS_SQLALCHEMY:
        with SessionLocal() as session:
            order = session.get(Order, oid)
            if order is None:
                return None
            for field in ["customer", "item", "quantity", "price", "status"]:
                if field in data:
                    setattr(order, field, data[field])
            order.total = round(int(order.quantity) * float(order.price), 2)
            session.commit()
            session.refresh(order)
            return _serialize(order)
    return None


def _delete_order(oid: int) -> dict | None:
    if _HAS_FLASK_SQLALCHEMY:
        order = db.session.get(Order, oid)
        if order is None:
            return None
        payload = _serialize(order)
        db.session.delete(order)
        db.session.commit()
        return payload
    if _HAS_SQLALCHEMY:
        with SessionLocal() as session:
            order = session.get(Order, oid)
            if order is None:
                return None
            payload = _serialize(order)
            session.delete(order)
            session.commit()
            return payload
    return None


# ─── Utility / demo endpoints ────────────────────────────────────────────────


@app.route("/api/health", methods=["GET"])
def health():
    import json

    redis_ok = False
    if _HAS_REDIS:
        try:
            redis_client.ping()
            redis_ok = True
        except Exception:
            redis_ok = False

    db_ok = False
    if _HAS_FLASK_SQLALCHEMY:
        try:
            db.session.execute(db.text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False
    elif _HAS_SQLALCHEMY:
        try:
            with SessionLocal() as session:
                session.execute(__import__("sqlalchemy").text("SELECT 1"))
            db_ok = True
        except Exception:
            db_ok = False

    return jsonify({
        "status": "UP" if (redis_ok and db_ok) else "DEGRADED",
        "redis": {"available": _HAS_REDIS, "ok": redis_ok, "url": REDIS_URL},
        "database": {
            "available": bool(_HAS_FLASK_SQLALCHEMY or _HAS_SQLALCHEMY),
            "ok": db_ok,
            "url": DATABASE_URL,
        },
        "celery": {"available": _HAS_CELERY},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


@app.route("/api/slow", methods=["GET"])
def slow_endpoint():
    logger.info("Slow endpoint called — sleeping 500ms")
    time.sleep(0.5)
    return jsonify({"message": "This was slow", "delay_ms": 500})


@app.route("/api/error", methods=["GET"])
def error_endpoint():
    logger.error("Intentional error triggered")
    abort(500, "Intentional error for demo purposes")


@app.route("/api/panic", methods=["GET"])
def panic_endpoint():
    """Trigger an unhandled ZeroDivisionError to test error tracking."""
    logger.error("Panic endpoint called — triggering ZeroDivisionError")
    # This will be captured by the error tracking inspector's Flask handler
    result = 1 / 0  # noqa: B018  (intentional zero-division for demo)
    return jsonify({"result": result})  # never reached


@app.route("/api/auth-check", methods=["GET"])
def auth_check():
    """Return auth configuration info (protected by X-API-Key)."""
    if not _check_api_key():
        abort(401, "Missing or invalid X-API-Key header")
    return jsonify({
        "authenticated": True,
        "scheme": "api_key",
        "header": "X-API-Key",
        "protected_paths": ["/api/orders"],
        "active_sessions": len(ACTIVE_SESSIONS),
    })


# ─── Main ────────────────────────────────────────────────────────────────────


if __name__ == "__main__":
    # Start the background cleanup scheduler
    _scheduler_timer = threading.Timer(30.0, _run_cleanup_loop)
    _scheduler_timer.daemon = True
    _scheduler_timer.start()

    print(
        "\n"
        "+-------------------------------------------------+\n"
        "|  Python Debug Agent v0.6.0 — Flask Demo          |\n"
        "|  Order Management API (Redis+SQLA+Celery)        |\n"
        "|                                                  |\n"
        "|  API:          http://localhost:8000/api/orders  |\n"
        "|  Health:       http://localhost:8000/api/health  |\n"
        "|  Auth Check:   http://localhost:8000/api/auth-check|\n"
        "|  Debug Agent:  http://localhost:8000/agent       |\n"
        "+-------------------------------------------------+\n"
        f"  Redis:        {_HAS_REDIS}  ({REDIS_URL})\n"
        f"  Celery:       {_HAS_CELERY}\n"
        f"  SQLAlchemy:   {_HAS_FLASK_SQLALCHEMY or _HAS_SQLALCHEMY}\n"
        f"  WebSocket:    {_HAS_FLASK_SOCK}  (/ws echo)\n"
        f"  Scheduler:    cleanup every 30s (background thread)\n"
        f"  Error Track:  sys.excepthook + Flask handler installed\n"
        f"  Feature Flags: new_ui=on, experimental_cache=off, ai_search=on\n"
        f"  Migrations:   schema v{_SCHEMA_VERSION} (1 pending)\n"
        f"  Locks:        order_counter (threading.Lock)\n"
        f"  API Key:      {API_KEY[:8]}... (set X-API-Key header)\n"
    )
    port = int(os.environ.get("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
