"""Endpoint testing inspector: HTTP requests against the running app.

Test your own app's endpoints from the debug agent:

    test_endpoint(method="GET", path="/api/health")
    batch_test_endpoints(tests=[...])

Uses ``urllib.request`` by default, or ``httpx`` if it is installed.
Route coverage is computed against Flask/Django URL maps.
"""

from __future__ import annotations

import json
import time
from typing import Any

from debug_agent.tool_registry import debug_tool, ToolParam


# ─── HTTP backend ──────────────────────────────────────────────────────────────


def _make_request(
    base_url: str,
    method: str,
    path: str,
    headers: dict[str, str] | None = None,
    body: Any = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Send an HTTP request and return a normalised response dict."""
    url = base_url.rstrip("/") + "/" + path.lstrip("/")

    # Prefer httpx if available
    try:
        import httpx  # type: ignore

        kwargs: dict[str, Any] = {"timeout": timeout}
        if body is not None:
            kwargs["json"] = body
        if headers:
            kwargs["headers"] = headers

        start = time.time()
        with httpx.Client() as client:
            resp = client.request(method.upper(), url, **kwargs)
        elapsed_ms = round((time.time() - start) * 1000, 2)

        resp_headers = dict(resp.headers)
        try:
            resp_body = resp.json()
        except Exception:
            resp_body = resp.text

        return {
            "status": resp.status_code,
            "headers": resp_headers,
            "body": resp_body,
            "duration_ms": elapsed_ms,
            "url": str(resp.url),
        }
    except ImportError:
        pass

    # Fallback: urllib.request
    import urllib.request
    import urllib.error

    data = None
    req_headers = dict(headers) if headers else {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        req_headers.setdefault("Content-Type", "application/json")

    req = urllib.request.Request(url, data=data, method=method.upper(), headers=req_headers)

    start = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            elapsed_ms = round((time.time() - start) * 1000, 2)
            raw = resp.read()
            resp_headers = dict(resp.headers)
            try:
                resp_body = json.loads(raw)
            except Exception:
                resp_body = raw.decode("utf-8", errors="replace")
            return {
                "status": resp.status,
                "headers": resp_headers,
                "body": resp_body,
                "duration_ms": elapsed_ms,
                "url": url,
            }
    except urllib.error.HTTPError as exc:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        raw = exc.read()
        resp_headers = dict(exc.headers) if exc.headers else {}
        try:
            resp_body = json.loads(raw)
        except Exception:
            resp_body = raw.decode("utf-8", errors="replace")
        return {
            "status": exc.code,
            "headers": resp_headers,
            "body": resp_body,
            "duration_ms": elapsed_ms,
            "url": url,
        }
    except urllib.error.URLError as exc:
        elapsed_ms = round((time.time() - start) * 1000, 2)
        return {
            "status": None,
            "error": f"URLError: {exc.reason}",
            "duration_ms": elapsed_ms,
            "url": url,
        }


def _resolve_base_url() -> str:
    """Guess the base URL for the running app."""
    import os
    port = os.environ.get("PORT", "8000")
    host = os.environ.get("HOST", "localhost")
    return os.environ.get("BASE_URL", f"http://{host}:{port}")


# ─── Route discovery ──────────────────────────────────────────────────────────


def _get_registered_routes() -> list[dict[str, Any]]:
    """Collect registered routes from Flask or Django if present."""
    routes: list[dict[str, Any]] = []

    # Flask
    try:
        import flask
        app = None
        try:
            app = flask.current_app._get_current_object()  # type: ignore[attr-defined]
        except Exception:
            pass
        if app is None:
            import sys
            for mod in list(sys.modules.values()):
                if mod is None or mod.__name__.startswith("debug_agent"):
                    continue
                for attr_name in dir(mod):
                    try:
                        obj = getattr(mod, attr_name)
                        if isinstance(obj, flask.Flask):
                            app = obj
                            break
                    except Exception:
                        continue
                if app:
                    break
        if app is not None:
            for rule in app.url_map.iter_rules():
                routes.append({
                    "rule": str(rule),
                    "endpoint": rule.endpoint,
                    "methods": sorted(rule.methods - {"HEAD", "OPTIONS"}),
                })
            return routes
    except ImportError:
        pass

    # Django
    try:
        from django.urls import get_resolver  # type: ignore

        resolver = get_resolver()
        for pattern in resolver.url_patterns:  # type: ignore[attr-defined]
            routes.append({
                "rule": str(pattern.pattern),
                "endpoint": getattr(pattern, "name", None),
                "methods": ["GET"],
            })
        return routes
    except Exception:
        pass

    return routes


# ─── Tools ────────────────────────────────────────────────────────────────────


@debug_tool(
    "test_endpoint",
    "Send an HTTP request to the running app and return status, headers, body, and duration",
)
def test_endpoint(
    method: str = ToolParam("HTTP method (GET, POST, PUT, DELETE, PATCH)"),
    path: str = ToolParam("Request path (e.g. '/api/health')"),
    headers: dict | None = None,
    body: Any = None,
    base_url: str | None = None,
    timeout: float = 0.0,
) -> dict:
    url = base_url or _resolve_base_url()
    to = timeout if timeout else 10.0

    try:
        return _make_request(url, method, path, headers, body, timeout=to)
    except Exception as exc:
        return {
            "status": None,
            "error": f"{type(exc).__name__}: {exc}",
            "url": f"{url.rstrip('/')}/{path.lstrip('/')}",
        }


@debug_tool(
    "batch_test_endpoints",
    "Test multiple endpoints with optional assertions in one call",
)
def batch_test_endpoints(
    tests: list[dict] = ToolParam("List of test dicts: {method, path, headers, body, expect_status, expect_body_contains}"),
    base_url: str | None = None,
) -> dict:
    url = base_url or _resolve_base_url()
    results: list[dict[str, Any]] = []
    passed = 0
    failed = 0

    for test in tests:
        method = test.get("method", "GET")
        path = test.get("path", "/")
        headers = test.get("headers")
        body = test.get("body")
        timeout = test.get("timeout", 10.0)

        resp = _make_request(url, method, path, headers, body, timeout=timeout)

        # Assertions
        assertions: list[dict[str, Any]] = []
        all_passed = True

        expected_status = test.get("expect_status")
        if expected_status is not None:
            ok = resp.get("status") == expected_status
            assertions.append({
                "type": "status",
                "expected": expected_status,
                "actual": resp.get("status"),
                "passed": ok,
            })
            all_passed = all_passed and ok

        expected_contains = test.get("expect_body_contains")
        if expected_contains is not None:
            resp_body = resp.get("body")
            body_str = json.dumps(resp_body) if not isinstance(resp_body, str) else resp_body
            ok = expected_contains in body_str
            assertions.append({
                "type": "body_contains",
                "expected": expected_contains,
                "passed": ok,
            })
            all_passed = all_passed and ok

        expected_header = test.get("expect_header")
        if expected_header:
            header_name, header_value = expected_header
            actual = resp.get("headers", {}).get(header_name)
            ok = actual == header_value
            assertions.append({
                "type": "header",
                "header": header_name,
                "expected": header_value,
                "actual": actual,
                "passed": ok,
            })
            all_passed = all_passed and ok

        max_duration = test.get("max_duration_ms")
        if max_duration is not None:
            actual_dur = resp.get("duration_ms")
            ok = actual_dur is not None and actual_dur <= max_duration
            assertions.append({
                "type": "max_duration",
                "expected": f"<= {max_duration}ms",
                "actual": f"{actual_dur}ms",
                "passed": ok,
            })
            all_passed = all_passed and ok

        if all_passed:
            passed += 1
        else:
            failed += 1

        results.append({
            "method": method,
            "path": path,
            "status": resp.get("status"),
            "duration_ms": resp.get("duration_ms"),
            "passed": all_passed,
            "assertions": assertions if assertions else None,
            "error": resp.get("error"),
        })

    return {
        "total": len(tests),
        "passed": passed,
        "failed": failed,
        "results": results,
    }


@debug_tool(
    "get_endpoint_coverage",
    "Compare registered Flask/Django routes against tested endpoints",
)
def get_endpoint_coverage(
    tested_paths: list | None = None,
) -> dict:
    routes = _get_registered_routes()

    if not routes:
        return {
            "total_routes": 0,
            "message": (
                "No Flask/Django app routes detected. "
                "Ensure the app is loaded and Flask/Django is installed."
            ),
        }

    tested = set(tested_paths or [])

    route_details: list[dict[str, Any]] = []
    covered = 0
    uncovered = 0

    for route in routes:
        rule = route["rule"]
        # Normalise: static rules match directly; parameterised rules
        # (e.g. /api/orders/<int:oid>) are marked as covered if a prefix
        # was tested.
        is_tested = False
        for tp in tested:
            if tp == rule:
                is_tested = True
                break
            # Prefix match for parameterised routes
            base_rule = rule.split("<")[0].rstrip("/")
            if tp.startswith(base_rule) and base_rule:
                is_tested = True
                break

        if is_tested:
            covered += 1
        else:
            uncovered += 1

        route_details.append({
            "rule": rule,
            "endpoint": route.get("endpoint"),
            "methods": route.get("methods", []),
            "tested": is_tested,
        })

    coverage_pct = round(covered / len(routes) * 100, 1) if routes else 0.0

    return {
        "total_routes": len(routes),
        "covered_routes": covered,
        "uncovered_routes": uncovered,
        "coverage_pct": coverage_pct,
        "tested_paths_provided": sorted(tested),
        "routes": route_details,
    }
