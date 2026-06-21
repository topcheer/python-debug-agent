"""Context compressor — summarizes older conversation rounds via LLM."""

from __future__ import annotations

import json
import logging
from typing import Any

from debug_agent.chat_session import ChatSession
from debug_agent.llm_client import LLMClient

logger = logging.getLogger("debug_agent")


class CompressionResult:
    def __init__(self, original_tokens: int, compressed_tokens: int, removed_rounds: int, strategy: str):
        self.original_tokens = original_tokens
        self.compressed_tokens = compressed_tokens
        self.removed_rounds = removed_rounds
        self.strategy = strategy


class ContextCompressor:
    def __init__(self, llm: LLMClient, model: str, temperature: float, max_context_tokens: int, recent_rounds_to_keep: int = 3):
        self.llm = llm
        self.model = model
        self.temperature = temperature
        self.max_context_tokens = max_context_tokens
        self.recent_rounds_to_keep = recent_rounds_to_keep

    def needs_compression(self, current_tokens: int) -> bool:
        return current_tokens > self.max_context_tokens * 0.75

    def compress(self, session: ChatSession) -> CompressionResult | None:
        original_tokens = session.get_current_context_tokens()
        if not self.needs_compression(original_tokens):
            return None

        rounds = self._identify_rounds(session.messages)

        keep_count = min(self.recent_rounds_to_keep, len(rounds) - 1)
        if keep_count < 1:
            return None

        summarize_count = len(rounds) - keep_count

        to_summarize = []
        for i in range(summarize_count):
            to_summarize.extend(rounds[i])

        to_keep = []
        for i in range(summarize_count, len(rounds)):
            to_keep.extend(rounds[i])

        try:
            summary = self._summarize_with_llm(to_summarize)
        except Exception as e:
            logger.warning(f"LLM summarization failed: {e}")
            summary = self._fallback_truncate(to_summarize)

        compressed = [
            {"role": "system", "content": f"[Previous conversation summary — {summarize_count} rounds compressed]\n\n{summary}"},
            *to_keep,
        ]
        compressed_tokens = self._estimate_tokens(compressed)
        session.replace_messages(compressed)

        return CompressionResult(original_tokens, compressed_tokens, summarize_count, f"LLM summarized {summarize_count} rounds")

    def _summarize_with_llm(self, old_messages: list[dict]) -> str:
        conversation_text = ""
        for msg in old_messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "user":
                conversation_text += f"[User] {content}\n\n"
            elif role == "assistant":
                if content:
                    conversation_text += f"[Assistant] {content}\n\n"
                for tc in msg.get("tool_calls", []):
                    fn = tc.get("function", {})
                    conversation_text += f"[Tool Call] {fn.get('name', '')}({fn.get('arguments', '')})\n\n"
            elif role == "tool":
                if len(content) > 2000:
                    content = content[:2000] + "...[truncated]"
                conversation_text += f"[Tool Result] {content}\n\n"

        prompt = """You are a conversation summarizer for a Python debugging assistant.
Summarize the KEY diagnostic findings from the conversation below concisely.

Focus on preserving:
- Problems investigated and their root causes (if found)
- Key tool results: actual numbers, statuses, error messages, configuration values
- Recommendations or fixes already suggested
- Any unresolved issues or follow-up actions pending

Rules:
- Be concise but preserve ALL important data points
- Use bullet points
- Do NOT include full JSON dumps
- Keep it under 600 words"""

        response = self.llm.chat(
            [
                {"role": "system", "content": prompt},
                {"role": "user", "content": f"Conversation to summarize:\n\n{conversation_text}"},
            ],
            tools=None,
        )
        return response["choices"][0]["message"]["content"]

    def _fallback_truncate(self, messages: list[dict]) -> str:
        sb = "Previous conversation summary (fallback):\n\n"
        for msg in messages:
            if msg.get("role") == "user" and msg.get("content"):
                q = msg["content"][:100] + "..." if len(msg["content"]) > 100 else msg["content"]
                sb += f"- User asked: {q}\n"
            if msg.get("role") == "assistant" and msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    sb += f"- Called tool: {tc.get('function', {}).get('name', '')}\n"
        return sb

    def _identify_rounds(self, messages: list[dict]) -> list[list[dict]]:
        rounds = []
        current = []
        has_assistant = False

        for msg in messages:
            role = msg.get("role", "")
            if role == "user":
                if current:
                    rounds.append(current)
                    current = []
                    has_assistant = False
                current.append(msg)
            elif role == "assistant":
                if has_assistant:
                    rounds.append(current)
                    current = []
                    has_assistant = False
                current.append(msg)
                has_assistant = True
            else:
                current.append(msg)

        if current:
            rounds.append(current)
        return rounds

    def _estimate_tokens(self, messages: list[dict]) -> int:
        chars = 0
        for msg in messages:
            chars += len(msg.get("content", "") or "")
            for tc in msg.get("tool_calls", []):
                fn = tc.get("function", {})
                chars += len(fn.get("name", "")) + len(fn.get("arguments", ""))
        return chars // 4
