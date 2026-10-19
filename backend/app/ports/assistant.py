"""Assistant port: a model that answers a question by calling read-only tools (BUILD_PLAN v2.3 change 25; ADR 0007).

The port owns the shape, not the rules. The tools arrive already bound to the logged-in
user (modules/assistant/tools.py), so a model can only see what that user could see on the
pages; none of them can change anything. The adapters run the tool loop; the service decides
what the answer may link to and checks its rupee figures.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

MAX_TOOL_ROUNDS = 6


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema of the arguments
    run: Callable[[dict[str, Any]], dict[str, Any]]  # bound to the user; returns JSON-safe data


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class Turn:
    role: Literal["user", "assistant"]
    text: str


@dataclass
class AssistantReply:
    answer: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model_id: str = ""
    prompt_version: str = ""


class AssistantUnavailable(Exception):
    """The model could not answer now (no key, outage, refusal, too many tool rounds).
    The panel says so; every page keeps working."""


class Assistant(Protocol):
    model_id: str

    def run(self, system: str, history: list[Turn], question: str, tools: list[ToolSpec]) -> AssistantReply: ...


def call_tool(tools: list[ToolSpec], name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Run one tool by name. Unknown tools and tool errors become data the model can read."""
    spec = next((t for t in tools if t.name == name), None)
    if spec is None:
        return {"error": f"No tool named {name}."}
    try:
        return spec.run(arguments or {})
    except Exception as exc:  # a tool's refusal (e.g. not found) is an answer, not a crash
        message = getattr(exc, "message", None) or str(exc) or type(exc).__name__
        return {"error": message}
