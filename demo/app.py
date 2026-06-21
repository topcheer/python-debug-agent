"""Demo: Order Management API with Debug Agent integrated (Flask).

Run:
    pip install -e ".[flask,dev]"
    LLM_API_KEY=your-key python demo/app.py

Then open http://localhost:8000/agent
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from datetime import datetime, timezone

from flask import Flask, jsonify, request, abort

from debug_agent.middleware import create_flask_blueprint
from debug_agent.inspectors.http_tracker import record_request

# ─── Structured logging ─────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("order_api")

# ─── Flask app ──────────────────────────────────────────────────────────────

app = Flask(__name__)

# ─── Debug Agent: one line to integrate ─────────────────────────────────────
app.register_blueprint(create_flask_blueprint())

# ─── In-memory order storage ────────────────────────────────────────────────

orders: dict[int, dict] = {}
_next_id = 1

# Seed 3 sample orders
_seed = [
    {"customer": "Alice Wang", "item": "MacBook Pro 16\"", "quantity": 1, "price": 2499.00},
    {"customer": "Bob Zhang", "item": "Logitech MX Master 3S", "quantity": 3, "price": 99.99},
    {"customer": "Charlie Li", "item": "Dell UltraSharp 32\" 4K", "quantity": 2, "price": 899.50},
]

for _s in _seed:
    oid = len(orders) + 1
    _s["id"] = oid
    _s["status"] = "confirmed"
    _s["created_at"] = datetime.now(timezone.utc).isoformat()
    _s["total"] = round(_s["quantity"] * _s["price"], 2)
    orders[oid] = _s
    _next_id = oid + 1

logger.info("Seeded %d sample orders", len(orders))


# ─── Simple cache for demonstration ─────────────────────────────────────────

_cache: dict[str, tuple[float, object]] = {}
_CACHE_TTL = 30.0  # seconds


def _cache_get(key: str):
    entry = _cache.get(key)
    if entry is None:
        return None
    ts, val = entry
    if time.time() - ts > _CACHE_TTL:
        _cache.pop(key, None)
        return None
    return val


def _cache_set(key: str, val):
    _cache[key] = (time.time(), val)


@lru_cache(maxsize=128)
def _expensive_computation(n: int) -> int:
    """Simulate an expensive computation for demo purposes."""
    logger.info("Computing fibonacci(%d) — cache miss", n)
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a


# ─── Request tracking middleware ────────────────────────────────────────────

@app.before_request
def _before():
    request._start_time = time.time()


@app.after_request
def _after(response):
    duration_ms = (time.time() - getattr(request, "_start_time", time.time())) * 1000
    client = request.remote_addr or ""
    record_request(request.method, request.path, response.status_code, duration_ms, client)
    return response


# ─── Error handlers ─────────────────────────────────────────────────────────

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found", "message": str(e.description)}), 404


@app.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Bad request", "message": str(e.description)}), 400


@app.errorhandler(500)
def internal_error(e):
    logger.error("Internal server error: %s", e)
    return jsonify({"error": "Internal server error", "message": str(e.description if hasattr(e, 'description') else e)}), 500


# ─── Order CRUD endpoints ───────────────────────────────────────────────────

@app.route("/api/orders", methods=["GET"])
def list_orders():
    cached = _cache_get("all_orders")
    if cached is not None:
        logger.info("Returning cached order list")
        return jsonify({"orders": cached, "count": len(cached), "cached": True})

    result = list(orders.values())
    _cache_set("all_orders", result)
    logger.info("Listing %d orders", len(result))
    return jsonify({"orders": result, "count": len(result), "cached": False})


@app.route("/api/orders", methods=["POST"])
def create_order():
    global _next_id
    data = request.get_json(silent=True)
    if not data:
        abort(400, "Request body must be JSON")

    required = ["customer", "item", "quantity", "price"]
    for field in required:
        if field not in data:
            abort(400, f"Missing required field: {field}")

    oid = _next_id
    _next_id += 1

    order = {
        "id": oid,
        "customer": data["customer"],
        "item": data["item"],
        "quantity": int(data["quantity"]),
        "price": float(data["price"]),
        "total": round(int(data["quantity"]) * float(data["price"]), 2),
        "status": data.get("status", "pending"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    orders[oid] = order
    _cache.pop("all_orders", None)  # invalidate cache

    logger.info("Created order #%d for %s — %s x%d", oid, order["customer"], order["item"], order["quantity"])
    return jsonify(order), 201


@app.route("/api/orders/<int:oid>", methods=["GET"])
def get_order(oid: int):
    cache_key = f"order_{oid}"
    cached = _cache_get(cache_key)
    if cached is not None:
        logger.info("Returning cached order #%d", oid)
        return jsonify(cached)

    if oid not in orders:
        abort(404, f"Order {oid} not found")

    _cache_set(cache_key, orders[oid])
    logger.info("Retrieved order #%d", oid)
    return jsonify(orders[oid])


@app.route("/api/orders/<int:oid>", methods=["PUT"])
def update_order(oid: int):
    if oid not in orders:
        abort(404, f"Order {oid} not found")

    data = request.get_json(silent=True)
    if not data:
        abort(400, "Request body must be JSON")

    order = orders[oid]
    for field in ["customer", "item", "quantity", "price", "status"]:
        if field in data:
            order[field] = data[field]

    # Recalculate total
    order["total"] = round(int(order["quantity"]) * float(order["price"]), 2)
    order["updated_at"] = datetime.now(timezone.utc).isoformat()

    _cache.pop("all_orders", None)
    _cache.pop(f"order_{oid}", None)

    logger.info("Updated order #%d — status=%s", oid, order.get("status"))
    return jsonify(order)


@app.route("/api/orders/<int:oid>", methods=["DELETE"])
def delete_order(oid: int):
    if oid not in orders:
        abort(404, f"Order {oid} not found")

    deleted = orders.pop(oid)
    _cache.pop("all_orders", None)
    _cache.pop(f"order_{oid}", None)

    logger.info("Deleted order #%d", oid)
    return jsonify({"deleted": oid, "customer": deleted["customer"]})


# ─── Utility / demo endpoints ───────────────────────────────────────────────

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({
        "status": "UP",
        "orders": len(orders),
        "cache_size": len(_cache),
        "fibonacci_cached": _expensive_computation.cache_info().currsize,
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


@app.route("/api/compute/<int:n>", methods=["GET"])
def compute_fibonacci(n: int):
    """Endpoint that demonstrates lru_cache."""
    if n > 500:
        abort(400, "n must be <= 500")
    result = _expensive_computation(n)
    info = _expensive_computation.cache_info()
    return jsonify({
        "n": n,
        "result": result,
        "cache_info": {
            "hits": info.hits,
            "misses": info.misses,
            "maxsize": info.maxsize,
            "currsize": info.currsize,
        },
    })


# ─── Main ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("""
+----------------------------------------------+
|  Python Debug Agent — Flask Demo             |
|  Order Management API                        |
|                                              |
|  API: http://localhost:8000/api/orders       |
|  Debug Agent: http://localhost:8000/agent    |
+----------------------------------------------+
    """)
    app.run(host="0.0.0.0", port=8000, debug=True)
