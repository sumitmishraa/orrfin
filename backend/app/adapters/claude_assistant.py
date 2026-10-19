"""Claude adapter for the Orrfin Assistant (Bedrock or the Anthropic API; ADR 0007).

A manual tool-use loop (the target model, Claude Sonnet 5.5, rejects forced tool_choice, so
`auto` is used and the system prompt steers). The assistant message is appended exactly as
returned (response.content), and every tool result of a round goes back in one user message.
`stop_reason` is checked before content is read: a refusal or a cut-off is "unavailable",
never a half answer.
"""

import json
from typing import Any

import anthropic

from app.adapters.ai_prompts import ASSISTANT_PROMPT_VERSION
from app.ports.assistant import MAX_TOOL_ROUNDS, AssistantReply, AssistantUnavailable, ToolCall, ToolSpec, Turn, call_tool


class ClaudeAssistant:
    def __init__(self, client: Any, model_id: str):
        self.client = client
        self.model_id = model_id

    def run(self, system: str, history: list[Turn], question: str, tools: list[ToolSpec]) -> AssistantReply:
        tool_defs = [{"name": t.name, "description": t.description, "input_schema": t.parameters} for t in tools]
        messages: list[dict[str, Any]] = [{"role": t.role, "content": t.text} for t in history]
        messages.append({"role": "user", "content": question})
        calls: list[ToolCall] = []
        for _ in range(MAX_TOOL_ROUNDS + 1):
            try:
                response = self.client.messages.create(model=self.model_id, max_tokens=16000, system=system,
                                                       tools=tool_defs, tool_choice={"type": "auto"}, messages=messages)
            except anthropic.APIStatusError as exc:
                raise AssistantUnavailable(f"Claude API error {exc.status_code}") from exc
            except anthropic.APIConnectionError as exc:
                raise AssistantUnavailable("Could not reach Claude.") from exc
            if response.stop_reason == "refusal":
                raise AssistantUnavailable("The model declined to answer this question.")
            if response.stop_reason == "max_tokens":
                raise AssistantUnavailable("The answer was cut off.")
            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if not text:
                    raise AssistantUnavailable("Claude returned no answer.")
                return AssistantReply(answer=text, tool_calls=calls, model_id=self.model_id,
                                      prompt_version=ASSISTANT_PROMPT_VERSION)
            messages.append({"role": "assistant", "content": response.content})
            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                arguments = dict(block.input or {})
                result = call_tool(tools, block.name, arguments)
                calls.append(ToolCall(block.name, arguments, result))
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(result),
                                "is_error": "error" in result})
            messages.append({"role": "user", "content": results})
        raise AssistantUnavailable(f"Stopped after {MAX_TOOL_ROUNDS} rounds of lookups without an answer.")
