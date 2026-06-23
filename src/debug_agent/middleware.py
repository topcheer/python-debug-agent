"""Framework integration: FastAPI, Starlette, Flask, Django middleware.

SSE events (Spring-aligned):
    content, tool_start, tool_result, done, error, context_compressed

Endpoints:
    GET  /agent           — Chat UI
    POST /agent/api/chat  — SSE streaming chat
    POST /agent/api/clear — Clear conversation
    GET  /agent/api/health — Health check
    GET  /agent/api/tools — List available tools
"""

from __future__ import annotations

import json
import queue
import threading
from typing import Any, Generator

from debug_agent.config import AgentConfig
from debug_agent.engine import DebugEngine, ChatCallback
from debug_agent.web.chat_page import render as render_chat_page

import logging
_logger = logging.getLogger(__name__)

# ==================== CORS Helper ====================

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization",
}


# ==================== Real-time SSE Callback ====================

class StreamingSseCallback(ChatCallback):
    """Bridges engine callbacks to a thread-safe queue for real-time SSE streaming.

    Unlike the old SseCallback that buffered all events, this pushes each event
    to a queue immediately, allowing the SSE generator to yield in real-time.
    """

    _SENTINEL = object()

    def __init__(self):
        self._queue: queue.Queue = queue.Queue()

    def on_content(self, chunk: str):
        self._queue.put(("content", json.dumps(chunk)))

    def on_tool_start(self, tool_name: str, args: str):
        self._queue.put(("tool_start", tool_name))

    def on_tool_result(self, tool_name: str, result: str):
        self._queue.put(("tool_result", f"{tool_name}: {result}"))

    def on_complete(self):
        self._queue.put(("done", ""))
        self._queue.put(self._SENTINEL)

    def on_error(self, message: str):
        self._queue.put(("error", message))
        self._queue.put(self._SENTINEL)

    def on_context_compressed(self, original_tokens: int, compressed_tokens: int, removed_rounds: int):
        info = json.dumps({"originalTokens": original_tokens, "compressedTokens": compressed_tokens, "removedRounds": removed_rounds})
        self._queue.put(("context_compressed", info))

    def stream(self) -> Generator[str, None, None]:
        """Generator that yields SSE lines in real-time as events arrive."""
        while True:
            item = self._queue.get(timeout=300)  # 5-min timeout
            if item is self._SENTINEL:
                break
            event_type, data = item
            yield f"event: {event_type}\ndata: {data}\n\n"


# ==================== FastAPI ====================

def create_fastapi_router(config: AgentConfig | None = None):
    """Create a FastAPI APIRouter with all debug agent endpoints."""
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
    from debug_agent import inspectors  # noqa: F401

    cfg = config or AgentConfig.from_env()
    engine = DebugEngine(cfg)
    router = APIRouter(prefix=cfg.base_path, tags=["Debug Agent"])

    @router.options("/{path:path}")
    async def cors_preflight(path: str):
        return JSONResponse({}, headers=CORS_HEADERS)

    @router.get("", response_class=HTMLResponse)
    async def chat_page():
        return HTMLResponse(render_chat_page(cfg.base_path), headers=CORS_HEADERS)

    @router.get("/")
    async def chat_page_slash():
        return HTMLResponse(render_chat_page(cfg.base_path), headers=CORS_HEADERS)

    @router.post("/api/chat")
    async def chat(request: Request):
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("sessionId", f"session-{id(request)}")

        cb = StreamingSseCallback()

        def run_engine():
            try:
                engine.chat(message, session_id, cb)
            except Exception as e:
                _logger.error("Engine error: %s", e)
                cb.on_error(str(e))

        worker = threading.Thread(target=run_engine, daemon=True)
        worker.start()

        return StreamingResponse(cb.stream(), media_type="text/event-stream", headers=CORS_HEADERS)

    @router.post("/api/clear")
    async def clear_conversation(request: Request):
        body = await request.json()
        session_id = body.get("sessionId", "")
        if session_id:
            engine.clear_session(session_id)
        return JSONResponse({"status": "cleared"}, headers=CORS_HEADERS)

    @router.get("/api/health")
    async def health():
        return JSONResponse({"status": "ok", "agent": "python-debug-agent"}, headers=CORS_HEADERS)

    @router.get("/api/tools")
    async def list_tools():
        return JSONResponse({"tools": engine.tools.all_schemas()}, headers=CORS_HEADERS)

    return router


# ==================== Starlette ====================

def create_starlette_app(config: AgentConfig | None = None):
    from starlette.applications import Starlette
    from starlette.responses import HTMLResponse, StreamingResponse, JSONResponse
    from starlette.routing import Route
    from debug_agent import inspectors  # noqa: F401

    cfg = config or AgentConfig.from_env()
    engine = DebugEngine(cfg)

    async def chat_page(request):
        return HTMLResponse(render_chat_page(cfg.base_path), headers=CORS_HEADERS)

    async def chat(request):
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("sessionId", f"session-{id(request)}")

        cb = StreamingSseCallback()

        def run_engine():
            try:
                engine.chat(message, session_id, cb)
            except Exception as e:
                _logger.error("Engine error: %s", e)
                cb.on_error(str(e))

        worker = threading.Thread(target=run_engine, daemon=True)
        worker.start()

        return StreamingResponse(cb.stream(), media_type="text/event-stream", headers=CORS_HEADERS)

    async def clear(request):
        body = await request.json()
        session_id = body.get("sessionId", "")
        if session_id:
            engine.clear_session(session_id)
        return JSONResponse({"status": "cleared"}, headers=CORS_HEADERS)

    async def health(request):
        return JSONResponse({"status": "ok", "agent": "python-debug-agent"}, headers=CORS_HEADERS)

    async def tools(request):
        return JSONResponse({"tools": engine.tools.all_schemas()}, headers=CORS_HEADERS)

    async def cors_options(request):
        return JSONResponse({}, headers=CORS_HEADERS)

    routes = [
        Route("/", chat_page),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/clear", clear, methods=["POST"]),
        Route("/api/health", health),
        Route("/api/tools", tools),
        Route("/{path:path}", cors_options, methods=["OPTIONS"]),
    ]
    return Starlette(routes=routes)


# ==================== Flask ====================

def create_flask_blueprint(config: AgentConfig | None = None):
    from flask import Blueprint, Response, request, jsonify
    from debug_agent import inspectors  # noqa: F401

    cfg = config or AgentConfig.from_env()
    engine = DebugEngine(cfg)

    bp = Blueprint("debug_agent", __name__, url_prefix=cfg.base_path)

    @bp.after_request
    def add_cors_headers(response):
        response.headers["Access-Control-Allow-Origin"] = "*"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    @bp.route("", methods=["GET", "OPTIONS"])
    @bp.route("/", methods=["GET", "OPTIONS"])
    def chat_page():
        if request.method == "OPTIONS":
            return "", 204
        return render_chat_page(cfg.base_path)

    @bp.route("/api/chat", methods=["POST", "OPTIONS"])
    def chat():
        if request.method == "OPTIONS":
            return "", 204

        message = request.json.get("message", "")
        session_id = request.json.get("sessionId", f"session-{id(request)}")

        cb = StreamingSseCallback()

        def run_engine():
            try:
                engine.chat(message, session_id, cb)
            except Exception as e:
                _logger.error("Engine error: %s", e)
                cb.on_error(str(e))

        worker = threading.Thread(target=run_engine, daemon=True)
        worker.start()

        return Response(cb.stream(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    @bp.route("/api/clear", methods=["POST", "OPTIONS"])
    def clear():
        if request.method == "OPTIONS":
            return "", 204
        session_id = request.json.get("sessionId", "")
        if session_id:
            engine.clear_session(session_id)
        return jsonify({"status": "cleared"})

    @bp.route("/api/health", methods=["GET"])
    def health():
        return jsonify({"status": "ok", "agent": "python-debug-agent"})

    @bp.route("/api/tools", methods=["GET"])
    def tools():
        return jsonify({"tools": engine.tools.all_schemas()})

    return bp


# ==================== Django ====================

def create_django_urls(config: AgentConfig | None = None):
    """Return a list of URL patterns for Django integration.

    Usage in urls.py:
        from debug_agent.middleware import create_django_urls
        urlpatterns += create_django_urls()
    """
    from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
    from django.urls import path
    from django.views.decorators.csrf import csrf_exempt
    import json as _json
    from debug_agent import inspectors  # noqa: F401

    cfg = config or AgentConfig.from_env()
    engine = DebugEngine(cfg)
    base = cfg.base_path.strip("/")

    def _cors(response):
        response["Access-Control-Allow-Origin"] = "*"
        response["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        response["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    @csrf_exempt
    def chat_page(request):
        if request.method == "OPTIONS":
            return _cors(HttpResponse(status=204))
        return _cors(HttpResponse(render_chat_page(cfg.base_path)))

    @csrf_exempt
    def chat(request):
        if request.method == "OPTIONS":
            return _cors(HttpResponse(status=204))
        body = _json.loads(request.body or b"{}")
        message = body.get("message", "")
        session_id = body.get("sessionId", f"session-{id(request)}")

        cb = StreamingSseCallback()

        def run_engine():
            try:
                engine.chat(message, session_id, cb)
            except Exception as e:
                _logger.error("Engine error: %s", e)
                cb.on_error(str(e))

        worker = threading.Thread(target=run_engine, daemon=True)
        worker.start()

        response = StreamingHttpResponse(cb.stream(), content_type="text/event-stream")
        return _cors(response)

    @csrf_exempt
    def clear(request):
        if request.method == "OPTIONS":
            return _cors(HttpResponse(status=204))
        body = _json.loads(request.body or b"{}")
        session_id = body.get("sessionId", "")
        if session_id:
            engine.clear_session(session_id)
        return _cors(JsonResponse({"status": "cleared"}))

    @csrf_exempt
    def health(request):
        return _cors(JsonResponse({"status": "ok", "agent": "python-debug-agent"}))

    @csrf_exempt
    def tools(request):
        return _cors(JsonResponse({"tools": engine.tools.all_schemas()}, json_dumps_params={"default": str}))

    return [
        path(f"{base}/", chat_page),
        path(f"{base}/api/chat", chat),
        path(f"{base}/api/clear", clear),
        path(f"{base}/api/health", health),
        path(f"{base}/api/tools", tools),
    ]
