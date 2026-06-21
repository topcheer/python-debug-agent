"""Tool framework: decorator-based registration and execution."""

from __future__ import annotations

import inspect as pyinspect
import json
import typing
from dataclasses import dataclass, field
from typing import Any, Callable, get_type_hints


@dataclass
class ToolParam:
    """Metadata for a tool parameter."""
    description: str = ""
    required: bool = True
    default: Any = None


@dataclass
class ToolDefinition:
    name: str
    description: str
    func: Callable
    params: dict[str, ToolParam] = field(default_factory=dict)

    def schema(self) -> dict:
        """Generate OpenAI function-calling schema."""
        hints = get_type_hints(self.func)
        sig = pyinspect.signature(self.func)
        properties = {}
        required = []

        for pname, param in sig.parameters.items():
            if pname == "ctx":
                continue
            ptype = hints.get(pname, str)
            json_type = _python_type_to_json(ptype)
            tp = self.params.get(pname)
            desc = tp.description if tp else ""
            properties[pname] = {"type": json_type, "description": desc}

            if param.default is pyinspect.Parameter.empty and (not tp or tp.required):
                required.append(pname)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def execute(self, **kwargs) -> Any:
        """Call the underlying function."""
        return self.func(**kwargs)


def _python_type_to_json(ptype) -> str:
    mapping = {int: "integer", float: "number", bool: "boolean", str: "string", list: "array", dict: "object"}
    return mapping.get(ptype, "string")


class ToolRegistry:
    """Global registry for debug tools."""

    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def get(self, name: str) -> ToolDefinition | None:
        return self._tools.get(name)

    def all_schemas(self) -> list[dict]:
        return [t.schema() for t in self._tools.values()]

    def execute(self, name: str, args: dict) -> Any:
        tool = self._tools.get(name)
        if not tool:
            return {"error": f"Unknown tool: {name}"}
        try:
            result = tool.execute(**args)
            return result
        except Exception as e:
            return {"error": str(e)}

    def names(self) -> list[str]:
        return list(self._tools.keys())


# Global singleton
registry = ToolRegistry()


def debug_tool(name: str, description: str, params: dict[str, ToolParam] | None = None):
    """Decorate a function to register it as a debug tool.

    Usage:
        @debug_tool("get_memory", "Get memory stats", {"detailed": ToolParam("Include details", required=False)})
        def get_memory(detailed: bool = False) -> dict:
            ...
    """

    def decorator(func: Callable) -> Callable:
        tool = ToolDefinition(
            name=name,
            description=description,
            func=func,
            params=params or {},
        )
        registry.register(tool)
        return func

    return decorator
