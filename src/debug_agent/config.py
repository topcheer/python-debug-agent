"""Configuration for Debug Agent."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    base_url: str = "https://open.bigmodel.cn/api/coding/paas/v4"
    api_key: str = ""
    model: str = "glm-5.2"
    temperature: float = 0.3
    max_tokens: int = 4096
    max_tool_rounds: int = 25
    timeout_seconds: int = 120
    max_retries: int = 3
    retry_base_delay_ms: int = 1000
    retry_max_delay_ms: int = 30000
    context_window_tokens: int = 100000


@dataclass
class AgentConfig:
    enabled: bool = True
    base_path: str = "/agent"
    llm: LLMConfig = field(default_factory=LLMConfig)

    @classmethod
    def from_env(cls) -> AgentConfig:
        return cls(
            enabled=os.getenv("DEBUG_AGENT_ENABLED", "true").lower() == "true",
            base_path=os.getenv("DEBUG_AGENT_BASE_PATH", "/agent"),
            llm=LLMConfig(
                base_url=os.getenv("LLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4"),
                api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY", ""),
                model=os.getenv("LLM_MODEL", "glm-5.2"),
                temperature=float(os.getenv("LLM_TEMPERATURE", "0.3")),
                max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
                max_tool_rounds=int(os.getenv("LLM_MAX_TOOL_ROUNDS", "25")),
                timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
                max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
                retry_base_delay_ms=int(os.getenv("LLM_RETRY_BASE_DELAY_MS", "1000")),
                retry_max_delay_ms=int(os.getenv("LLM_RETRY_MAX_DELAY_MS", "30000")),
                context_window_tokens=int(os.getenv("LLM_CONTEXT_WINDOW_TOKENS", "100000")),
            ),
        )
