"""OpenAI-compatible LLM client with real streaming, retry, and token usage tracking."""

from __future__ import annotations

import json
import logging
import random
import time
from typing import Any, Callable

import httpx

from debug_agent.config import LLMConfig

logger = logging.getLogger("debug_agent")


class StreamHandler:
    """Low-level stream callback interface (engine implements this)."""

    def on_content(self, chunk: str): ...
    def on_complete(self, tool_calls: list[dict], finish_reason: str | None, usage: dict | None): ...
    def on_error(self, error: Exception): ...


class LLMClient:
    """OpenAI-compatible chat client with real streaming and retry."""

    def __init__(self, config: LLMConfig):
        self.cfg = config
        self.client = httpx.Client(timeout=config.timeout_seconds)

    # ==================== Non-Streaming ====================

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> dict:
        """Non-streaming chat completion with retry."""
        body: dict = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 1024,
        }
        if tools:
            body["tools"] = tools

        return self._post_with_retry("/chat/completions", body)

    # ==================== Streaming ====================

    def chat_stream_raw(self, messages: list[dict], tools: list[dict] | None, tool_choice: Any, handler: StreamHandler):
        """Streaming chat completion with retry. Calls handler callbacks."""
        body: dict = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": self.cfg.max_tokens,
            "stream": True,
            "stream_options": {"include_usage": True},
        }
        if tools:
            body["tools"] = tools
        if tool_choice:
            body["tool_choice"] = tool_choice

        max_retries = self.cfg.max_retries
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                self._stream_request("/chat/completions", body, handler)
                return
            except Exception as e:
                last_error = e
                if self._is_retriable(e) and attempt < max_retries:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay / 1000.0)
                    continue
                handler.on_error(e)
                return

        handler.on_error(Exception(f"Exhausted retries after {max_retries} attempts: {last_error}"))

    # ==================== Stream Processing ====================

    def _stream_request(self, path: str, body: dict, handler: StreamHandler):
        url = f"{self.cfg.base_url}{path}"

        with self.client.stream("POST", url, headers=self._headers(), json=body) as resp:
            if resp.status_code >= 400:
                error_body = resp.read().decode()
                raise RetriableError(resp.status_code, f"HTTP {resp.status_code}: {error_body}")

            tool_call_map: dict[int, dict] = {}
            finish_reason = None
            usage = None

            for line in resp.iter_lines():
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    continue

                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                if chunk.get("usage") and chunk["usage"].get("prompt_tokens"):
                    usage = chunk["usage"]

                choices = chunk.get("choices", [])
                if not choices:
                    continue

                choice = choices[0]
                delta = choice.get("delta", {})

                if delta.get("content"):
                    handler.on_content(delta["content"])

                if delta.get("tool_calls"):
                    for tc in delta["tool_calls"]:
                        idx = tc.get("index", 0)
                        if idx not in tool_call_map:
                            tool_call_map[idx] = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        entry = tool_call_map[idx]
                        if tc.get("id"):
                            entry["id"] = tc["id"]
                        if tc.get("type"):
                            entry["type"] = tc["type"]
                        fn = tc.get("function", {})
                        if fn.get("name"):
                            entry["function"]["name"] += fn["name"]
                        if fn.get("arguments") is not None:
                            entry["function"]["arguments"] += fn["arguments"]

                if choice.get("finish_reason"):
                    finish_reason = choice["finish_reason"]

            tool_calls = [tool_call_map[k] for k in sorted(tool_call_map.keys()) if tool_call_map[k]["function"]["name"]]
            handler.on_complete(tool_calls, finish_reason, usage)

    # ==================== Non-Streaming POST with retry ====================

    def _post_with_retry(self, path: str, body: dict) -> dict:
        max_retries = self.cfg.max_retries
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                url = f"{self.cfg.base_url}{path}"
                resp = self.client.post(url, headers=self._headers(), json=body)
                if resp.status_code >= 400:
                    raise RetriableError(resp.status_code, f"HTTP {resp.status_code}: {resp.text}")
                return resp.json()
            except Exception as e:
                last_error = e
                if self._is_retriable(e) and attempt < max_retries:
                    delay = self._calculate_delay(attempt)
                    time.sleep(delay / 1000.0)
                    continue
                raise

        raise last_error

    # ==================== Helpers ====================

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.cfg.api_key}", "Content-Type": "application/json"}

    def _is_retriable(self, error: Exception) -> bool:
        if isinstance(error, RetriableError):
            return error.is_retriable()
        return True  # Network errors

    def _calculate_delay(self, attempt: int) -> int:
        base = self.cfg.retry_base_delay_ms * (2 ** attempt)
        jitter = random.randint(0, base // 2)
        delay = base + jitter
        return min(delay, self.cfg.retry_max_delay_ms)

    def close(self):
        self.client.close()


class RetriableError(Exception):
    """HTTP error that can be retried."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code

    def is_retriable(self) -> bool:
        return self.status_code in (429, 500, 502, 503, 504)
