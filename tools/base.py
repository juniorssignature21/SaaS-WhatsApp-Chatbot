from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class ToolContext:
    business: Any
    conversation: Any
    customer: Any
    # Filled by tools that change conversation state (e.g. handoff).
    effects: dict = field(default_factory=dict)


@dataclass
class ToolResult:
    content: str
    is_error: bool = False


@dataclass
class ToolSpec:
    name: str
    description: str
    input_schema: dict
    handler: Callable[[ToolContext, dict], ToolResult]

    def to_api(self):
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema}
