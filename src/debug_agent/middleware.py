"""Framework integration: FastAPI, Starlette, Flask middleware.

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
from typing import Any

from debug_agent.config import AgentConfig
from debug_agent.engine import DebugEngine, ChatCallback
from debug_agent.web.chat_page import render as render_chat_page


# ==================== SSE Callback ====================

class SseCallback(ChatCallback):
    """Bridges engine callbacks to SSE event lines."""

    def __init__(self):
        self.events: list[tuple[str, str]] = []

    def on_content(self, chunk: str):
        self.events.append(("content", json.dumps(chunk)))

    def on_tool_start(self, tool_name: str, args: str):
        self.events.append(("tool_start", tool_name))

    def on_tool_result(self, tool_name: str, result: str):
        self.events.append(("tool_result", f"{tool_name}: {result}"))

    def on_complete(self):
        self.events.append(("done", ""))

    def on_error(self, message: str):
        self.events.append(("error", message))

    def on_context_compressed(self, original_tokens: int, compressed_tokens: int, removed_rounds: int):
        info = json.dumps({"originalTokens": original_tokens, "compressedTokens": compressed_tokens, "removedRounds": removed_rounds})
        self.events.append(("context_compressed", info))


# ==================== FastAPI ====================

def create_fastapi_router(config: AgentConfig | None = None):
    """Create a FastAPI APIRouter with all debug agent endpoints."""
    from fastapi import APIRouter, Request
    from fastapi.responses import HTMLResponse, StreamingResponse
    from debug_agent import inspectors  # noqa: F401

    cfg = config or AgentConfig.from_env()
    engine = DebugEngine(cfg)
    router = APIRouter(prefix=cfg.base_path, tags=["Debug Agent"])

    @router.get("", response_class=HTMLResponse)
    async def chat_page():
        return render_chat_page(cfg.base_path)

    @router.get("/")
    async def chat_page_slash():
        return render_chat_page(cfg.base_path)

    @router.post("/api/chat")
    async def chat(request: Request):
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("sessionId", f"session-{id(request)}")

        def event_stream():
            cb = SseCallback()
            engine.chat(message, session_id, cb)
            for event_type, data in cb.events:
                yield f"event: {event_type}\ndata: {data}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    @router.post("/api/clear")
    async def clear_conversation(request: Request):
        body = await request.json()
        session_id = body.get("sessionId", "")
        if session_id:
            engine.clear_session(session_id)
        return {"status": "cleared"}

    @router.get("/api/health")
    async def health():
        return {"status": "ok", "agent": "python-debug-agent"}

    @router.get("/api/tools")
    async def list_tools():
        return {"tools": engine.tools.all_schemas()}

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
        return HTMLResponse(render_chat_page(cfg.base_path))

    async def chat(request):
        body = await request.json()
        message = body.get("message", "")
        session_id = body.get("sessionId", f"session-{id(request)}")

        def event_stream():
            cb = SseCallback()
            engine.chat(message, session_id, cb)
            for event_type, data in cb.events:
                yield f"event: {event_type}\ndata: {data}\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    async def clear(request):
        body = await request.json()
        session_id = body.get("sessionId", "")
        if session_id:
            engine.clear_session(session_id)
        return JSONResponse({"status": "cleared"})

    async def health(request):
        return JSONResponse({"status": "ok", "agent": "python-debug-agent"})

    async def tools(request):
        return JSONResponse({"tools": engine.tools.all_schemas()})

    routes = [
        Route("/", chat_page),
        Route("/api/chat", chat, methods=["POST"]),
        Route("/api/clear", clear, methods=["POST"]),
        Route("/api/health", health),
        Route("/api/tools", tools),
    ]
    return Starlette(routes=routes)


# ==================== Flask ====================

def create_flask_blueprint(config: AgentConfig | None = None):
    from flask import Blueprint, Response, request, jsonify
    from debug_agent import inspectors  # noqa: F401

    cfg = config or AgentConfig.from_env()
    engine = DebugEngine(cfg)

    bp = Blueprint("debug_agent", __name__, url_prefix=cfg.base_path)

    @bp.route("", methods=["GET"])
    @bp.route("/", methods=["GET"])
    def chat_page():
        return render_chat_page(cfg.base_path)

    @bp.route("/api/chat", methods=["POST"])
    def chat():
        message = request.json.get("message", "")
        session_id = request.json.get("sessionId", f"session-{id(request)}")

        def generate():
            cb = SseCallback()
            engine.chat(message, session_id, cb)
            for event_type, data in cb.events:
                yield f"event: {event_type}\ndata: {data}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    @bp.route("/api/clear", methods=["POST"])
    def clear():
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
