"""Chat session management with token tracking."""

from __future__ import annotations

import time
from typing import Any


class ChatSession:
    """Manages conversation history and cumulative token usage."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.created_at = time.time()
        self.messages: list[dict[str, Any]] = []
        self.last_active_at = self.created_at

        self.last_token_usage: dict | None = None
        self.cumulative_prompt_tokens: int = 0
        self.cumulative_completion_tokens: int = 0

    def add_message(self, message: dict[str, Any]):
        self.messages.append(message)
        self.last_active_at = time.time()

    def replace_messages(self, new_messages: list[dict[str, Any]]):
        self.messages = new_messages
        self.last_active_at = time.time()

    def record_token_usage(self, usage: dict | None):
        if not usage:
            return
        self.last_token_usage = usage
        self.cumulative_prompt_tokens = usage.get("prompt_tokens", 0)
        self.cumulative_completion_tokens += usage.get("completion_tokens", 0)

    def get_current_context_tokens(self) -> int:
        return self.cumulative_prompt_tokens

    def clear(self):
        self.messages = []
        self.last_token_usage = None
        self.cumulative_prompt_tokens = 0
        self.cumulative_completion_tokens = 0
        self.last_active_at = time.time()
