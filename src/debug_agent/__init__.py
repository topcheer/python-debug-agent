"""Debug Agent — AI-powered runtime debugging for Python applications."""

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
