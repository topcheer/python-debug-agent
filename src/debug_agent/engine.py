"""Debug engine — the reasoning loop that connects LLM to tools.

Spring-aligned: dynamic system prompt, ChatSession, ContextCompressor, real streaming.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from debug_agent.chat_session import ChatSession
from debug_agent.config import AgentConfig
from debug_agent.context_compressor import ContextCompressor
from debug_agent.llm_client import LLMClient, StreamHandler
from debug_agent.system_prompt_builder import SystemPromptBuilder
from debug_agent.tool_registry import registry

logger = logging.getLogger("debug_agent")


class ChatCallback:
    """Engine to UI streaming callback."""

    def on_content(self, chunk: str): ...
    def on_tool_start(self, tool_name: str, args: str): ...
    def on_tool_result(self, tool_name: str, result: str): ...
    def on_complete(self): ...
    def on_error(self, message: str): ...
    def on_context_compressed(self, original_tokens: int, compressed_tokens: int, removed_rounds: int): ...


class _EngineStreamHandler(StreamHandler):
    """StreamHandler implementation used internally by the engine."""

    def __init__(self, cb: ChatCallback):
        self._cb = cb
        self.tool_calls: list[dict] = []
        self.usage: dict | None = None
        self.had_error = False
        self.content = ""

    def on_content(self, chunk: str):
        self.content += chunk
        self._cb.on_content(chunk)

    def on_complete(self, tool_calls: list[dict], finish_reason: str | None, usage: dict | None):
        self.tool_calls = tool_calls
        self.usage = usage

    def on_error(self, error: Exception):
        self.had_error = True
        self._cb.on_error(f"LLM API error: {error}")


class DebugEngine:
    """Orchestrates the LLM Tool reasoning loop."""

    def __init__(self, config: AgentConfig):
        self.config = config
        self.llm = LLMClient(config.llm)
        self.tools = registry
        self._sessions: dict[str, ChatSession] = {}

        self.prompt_builder = SystemPromptBuilder(registry)
        self.system_prompt = self.prompt_builder.build()
        self.context_compressor = ContextCompressor(
            self.llm, config.llm.model, config.llm.temperature, config.llm.context_window_tokens,
        )

    def chat(self, message: str, session_id: str = "default", callback: ChatCallback | None = None):
        """Process a user message with streaming via callback."""
        if callback is None:
            callback = ChatCallback()

        session = self._get_or_create_session(session_id)
        session.add_message({"role": "user", "content": message})
        self._run_tool_loop(session, callback)

    def clear_session(self, session_id: str = "default"):
        session = self._sessions.get(session_id)
        if session:
            session.clear()

    def _get_or_create_session(self, session_id: str) -> ChatSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = ChatSession(session_id)
        return self._sessions[session_id]

    # ==================== Core Tool-Calling Loop ====================

    def _run_tool_loop(self, session: ChatSession, cb: ChatCallback):
        max_rounds = self.config.llm.max_tool_rounds

        for round_num in range(max_rounds):
            # Context compression check
            if round_num > 0 and self.context_compressor.needs_compression(session.get_current_context_tokens()):
                result = self.context_compressor.compress(session)
                if result:
                    cb.on_content(
                        f"\n\n> [Context auto-compressed: {result.original_tokens}"
                        f" -> ~{result.compressed_tokens} tokens ({result.strategy})]\n\n"
                    )
                    cb.on_context_compressed(result.original_tokens, result.compressed_tokens, result.removed_rounds)

            messages = [{"role": "system", "content": self.system_prompt}] + session.messages
            tool_schemas = self.tools.all_schemas()

            handler = _EngineStreamHandler(cb)
            self.llm.chat_stream_raw(messages, tool_schemas, "auto", handler)

            if handler.had_error:
                return

            if handler.usage:
                session.record_token_usage(handler.usage)

            if not handler.tool_calls:
                # If empty content after tool calls, prompt LLM to summarize
                if not handler.content.strip() and round_num > 0:
                    session.add_message({
                        "role": "user",
                        "content": (
                            "Based on all the diagnostic data you've gathered from the tools above, "
                            "please provide a comprehensive analysis of the findings and "
                            "actionable recommendations."
                        ),
                    })
                    messages = [{"role": "system", "content": self.system_prompt}] + session.messages
                    summarize_handler = _EngineStreamHandler(cb)
                    self.llm.chat_stream_raw(messages, [], "none", summarize_handler)
                    session.add_message({"role": "assistant", "content": summarize_handler.content})
                else:
                    session.add_message({"role": "assistant", "content": handler.content})
                cb.on_complete()
                return

            # Execute tool calls
            session.add_message({
                "role": "assistant",
                "content": handler.content,
                "tool_calls": handler.tool_calls,
            })

            for tc in handler.tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}

                cb.on_tool_start(tool_name, tc["function"]["arguments"])

                result = self.tools.execute(tool_name, args)
                result_str = json.dumps(result, default=str, ensure_ascii=False)
                if len(result_str) > 12000:
                    result_str = result_str[:12000]

                cb.on_tool_result(tool_name, result_str)
                session.add_message({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_str,
                })

        # Max rounds - force final summary
        final_messages = [{"role": "system", "content": self.system_prompt}] + session.messages
        final_messages.append({
            "role": "system",
            "content": (
                "You have reached the maximum number of tool-calling rounds. "
                "Based on all the diagnostic data you have gathered so far, "
                "provide a comprehensive analysis and actionable recommendations NOW. "
                "Do not attempt to call more tools."
            ),
        })

        handler = _EngineStreamHandler(cb)
        self.llm.chat_stream_raw(final_messages, [], "none", handler)
        cb.on_complete()
