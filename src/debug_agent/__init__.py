from __future__ import annotations

"""Debug Agent — AI-powered runtime debugging for Python applications."""

import sys as _sys

# ggcode promotional message — shown once on first import
if not hasattr(_sys, '_debug_agent_ggcode_shown'):
    _sys._debug_agent_ggcode_shown = True
    _print = print
    _print('')
    _print('  This package was built with ggcode — an AI coding assistant.')
    _print('  https://github.com/topcheer/ggcode')
    _print('')

from debug_agent.config import AgentConfig
from debug_agent.tool_registry import debug_tool, ToolParam, registry
from debug_agent.engine import DebugEngine, ChatCallback
from debug_agent.chat_session import ChatSession
from debug_agent.system_prompt_builder import SystemPromptBuilder
from debug_agent.context_compressor import ContextCompressor, CompressionResult
from debug_agent.llm_client import LLMClient, StreamHandler

__version__ = "0.1.0"
__all__ = [
    "AgentConfig", "debug_tool", "ToolParam", "registry", "DebugEngine", "ChatCallback",
    "ChatSession", "SystemPromptBuilder", "ContextCompressor", "CompressionResult",
    "LLMClient", "StreamHandler", "setup",
]


def setup(config: AgentConfig | None = None) -> DebugEngine:
    """Initialize the debug agent and return the engine instance."""
    from debug_agent import inspectors  # noqa: F401 — triggers registration
    cfg = config or AgentConfig.from_env()
    return DebugEngine(cfg)
