"""Scripted stand-in for the assistant model, for tests and the evaluation set (ADR 0003 pattern).

It is not a model: it calls the scripted tools in order through the real, user-bound tool
functions, then writes the answer with a function of the results. That exercises everything
around the model (scope, links, the ₹ check, logging) without a network call.
"""

from collections.abc import Callable
from typing import Any

from app.ports.assistant import AssistantReply, AssistantUnavailable, ToolCall, ToolSpec, Turn, call_tool


class FakeAssistant:
    model_id = "fake-assistant (scripted, not an AI model)"

    def __init__(self, steps: list[tuple[str, dict[str, Any]]],
                 answer: Callable[[list[ToolCall]], str], *, fail: bool = False):
        self.steps = steps
        self.answer = answer
        self.fail = fail
        self.seen_system = ""
        self.seen_question = ""

    def run(self, system: str, history: list[Turn], question: str, tools: list[ToolSpec]) -> AssistantReply:
        if self.fail:
            raise AssistantUnavailable("Simulated outage.")
        self.seen_system, self.seen_question = system, question
        calls = [ToolCall(name, args, call_tool(tools, name, args)) for name, args in self.steps]
        return AssistantReply(answer=self.answer(calls), tool_calls=calls, model_id=self.model_id,
                              prompt_version="fake")



class FakeDrafter:
    """Scripted drafter for tests: returns the given JSON / text, or fails like an outage."""
    model_id = "fake-drafter (scripted, not an AI model)"

    def __init__(self, json_out: dict[str, Any] | None = None, text_out: str = "", *, fail: bool = False):
        self.json_out, self.text_out, self.fail = json_out or {}, text_out, fail
        self.seen: list[str] = []

    def json(self, system: str, text: str, schema: dict[str, Any]) -> dict[str, Any]:
        self.seen.append(text)
        if self.fail:
            raise AssistantUnavailable("Simulated outage.")
        return self.json_out

    def text(self, system: str, text: str) -> str:
        self.seen.append(text)
        if self.fail:
            raise AssistantUnavailable("Simulated outage.")
        return self.text_out
