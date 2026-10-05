from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class ToolDeclaration:
    name: str
    description: str
    input_schema: dict
    execution: Literal["read", "exclusive"]
    invoke: Callable[[dict, Any], Awaitable[dict]]

    def register(self, api):
        api.register_tool(self)


def schema(properties, required=()):
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


def field(kind, description, **constraints):
    return {"type": kind, "description": description, **constraints}
