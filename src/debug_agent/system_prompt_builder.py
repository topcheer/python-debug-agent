"""Dynamic system prompt builder — generates prompt from registered tools."""

from __future__ import annotations

from debug_agent.tool_registry import registry

CATEGORY_MAP = {
    # Memory & GC
    "heap": "Memory & GC",
    "gc": "Memory & GC",
    "memory": "Memory & GC",
    "tracemalloc": "Memory & GC",
    "object_count": "Memory & GC",
    "ref_cycle": "Memory & GC",
    "leak": "Memory & GC",
    "snapshot": "Memory & Snapshots",
    "compare": "Memory & Snapshots",
    # Process & Runtime
    "process": "Process Info",
    "runtime": "Runtime Info",
    "system": "System Info",
    "cpu": "System Info",
    "disk": "System Info",
    "uptime": "System Info",
    "pid": "Process Info",
    # Threads & Locks
    "thread": "Threads & Locks",
    "lock": "Threads & Locks",
    "deadlock": "Threads & Locks",
    "contention": "Threads & Locks",
    "async": "Async Tasks",
    "event_loop": "Async Tasks",
    # Framework
    "routes": "Framework",
    "middleware": "Framework",
    "framework": "Framework",
    "flask": "Framework",
    "django": "Framework",
    "fastapi": "Framework",
    "signals": "Framework",
    # HTTP
    "recent": "HTTP Requests",
    "slow": "HTTP Requests",
    "request": "HTTP Requests",
    "http": "HTTP Requests",
    "outbound": "HTTP Requests",
    # Database
    "sqlalchemy": "Database",
    "db": "Database",
    "migration": "Database Migration",
    "pending": "Database Migration",
    # Modules & Dependencies
    "module": "Modules",
    "import": "Modules",
    "package": "Dependencies",
    "installed": "Dependencies",
    "environment": "Environment & Config",
    # Configuration
    "config": "Configuration",
    "env": "Configuration",
    # Cache
    "cache": "Cache",
    # Health & Security
    "health": "Health Checks",
    "auth": "Security",
    "cors": "Security",
    # Error Tracking
    "error": "Error Tracking",
    "warning": "Error Tracking",
    "exception": "Error Tracking",
    # WebSocket
    "ws": "WebSocket",
    "websocket": "WebSocket",
    # Profiling
    "start": "Profiling",
    "stop": "Profiling",
    "top": "Profiling",
    "profile": "Profiling",
    # Feature Flags
    "feature": "Feature Flags",
    "flag": "Feature Flags",
    "evaluate": "Feature Flags",
    # Endpoint Testing
    "test": "Endpoint Testing",
    "batch": "Endpoint Testing",
    "endpoint": "Endpoint Testing",
    "coverage": "Endpoint Testing",
    # Connection Pool
    "pool": "Connection Pool",
    "connection": "Connection Pool",
    # File Descriptors
    "fd": "File Descriptors",
    "handle": "File Descriptors",
    # Metrics
    "metric": "Metrics",
    "counter": "Metrics",
    # Build & Deployment
    "build": "Build & Deployment",
    "deployment": "Build & Deployment",
    "version": "Build & Deployment",
    # Service Registry
    "registered": "Service Registry",
    "service": "Service Registry",
    # Celery / Queue
    "celery": "Job Queue",
    "queue": "Job Queue",
    "task": "Async Tasks",
    "job": "Job Queue",
    # Redis
    "redis": "Redis",
    # Logging
    "log": "Logging",
}


class SystemPromptBuilder:
    """Builds system prompt dynamically from registered tools."""

    def __init__(self, tool_registry=registry):
        self.registry = tool_registry

    def build(self) -> str:
        categories = self._categorize_tools()

        sb = "You are an expert Python runtime debugging assistant.\n"
        sb += "You are running INSIDE the developer's Python application and have direct access\n"
        sb += "to its runtime state through diagnostic tools.\n\n"
        sb += "## Your Capabilities\n"
        sb += "You can call tools to inspect the live application. Here are ALL available tools,\n"
        sb += "grouped by category:\n\n"

        for category in sorted(categories.keys()):
            tools = categories[category]
            sb += f"**{category}**\n"
            for tool in tools:
                sb += f"- `{tool['name']}`: {self._truncate(tool['description'])}\n"
            sb += "\n"

        sb += "## Workflow\n"
        sb += "1. Understand the developer's problem description\n"
        sb += "2. Proactively call the most relevant tools to gather diagnostic data\n"
        sb += "3. Analyze the collected data to identify root causes\n"
        sb += "4. Provide clear, actionable solutions with data evidence\n\n"
        sb += "## Guidelines\n"
        sb += "- Be proactive: gather data with tools before answering\n"
        sb += "- Always present data in a readable format (tables, bullet points)\n"
        sb += "- Respond in the same language the developer uses\n"
        sb += "- When you find a problem, explain the root cause and give concrete fix suggestions\n"
        sb += "- You can call multiple tools in parallel if they are independent\n"

        return sb

    def _categorize_tools(self) -> dict[str, list[dict]]:
        categories: dict[str, list[dict]] = {}
        for schema in self.registry.all_schemas():
            fn = schema["function"]
            name = fn["name"]
            desc = fn["description"]
            category = self._extract_category(name)
            if category not in categories:
                categories[category] = []
            categories[category].append({"name": name, "description": desc})
        return categories

    def _extract_category(self, tool_name: str) -> str:
        name_lower = tool_name.lower()
        for keyword, category in CATEGORY_MAP.items():
            if keyword in name_lower:
                return category
        return "Other Tools"

    def _truncate(self, desc: str) -> str:
        if not desc:
            return ""
        period = desc.find(".")
        if 0 < period < 150:
            return desc[: period + 1]
        return desc[:120] + "..." if len(desc) > 120 else desc
