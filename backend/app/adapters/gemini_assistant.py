"""Gemini adapter for the Orrfin Assistant (ADR 0005, ADR 0007).

Manual function calling: automatic calling is switched off, so this loop runs every tool
itself, records each call, and stops after MAX_TOOL_ROUNDS. The model's own content
(including any thought signatures) is appended back unchanged before the tool results,
as multi-turn function calling requires.
"""

import json
import time
from typing import Any

from google.genai import errors, types

from app.adapters.ai_prompts import ASSISTANT_PROMPT_VERSION
from app.ports.assistant import MAX_TOOL_ROUNDS, AssistantReply, AssistantUnavailable, ToolCall, ToolSpec, Turn, call_tool


RETRY_PAUSE_SECONDS = 2.0


class GeminiAssistant:
    def __init__(self, client: Any, model_id: str):
        self.client = client
        self.model_id = model_id

    def run(self, system: str, history: list[Turn], question: str, tools: list[ToolSpec]) -> AssistantReply:
        declarations = [types.FunctionDeclaration(name=t.name, description=t.description,
                                                  parameters_json_schema=t.parameters) for t in tools]
        config = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=declarations)],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=4000,
        )
        contents: list[Any] = [types.Content(role="user" if t.role == "user" else "model",
                                             parts=[types.Part.from_text(text=t.text)]) for t in history]
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=question)]))
        calls: list[ToolCall] = []
        for _ in range(MAX_TOOL_ROUNDS + 1):
            response = self._generate(contents, config)
            candidate = (response.candidates or [None])[0]
            if candidate is None or candidate.content is None:
                raise AssistantUnavailable("Gemini returned no answer.")
            function_calls = response.function_calls or []
            if not function_calls:
                text = (response.text or "").strip()
                if not text:
                    raise AssistantUnavailable(f"No usable answer (finish_reason={candidate.finish_reason}).")
                return AssistantReply(answer=text, tool_calls=calls, model_id=self.model_id,
                                      prompt_version=ASSISTANT_PROMPT_VERSION)
            contents.append(candidate.content)
            parts = []
            for fc in function_calls:
                arguments = dict(fc.args or {})
                result = call_tool(tools, fc.name, arguments)
                calls.append(ToolCall(fc.name, arguments, result))
                # Round-trip through JSON so the SDK gets plain types only.
                parts.append(types.Part.from_function_response(name=fc.name, response=json.loads(json.dumps(result))))
            contents.append(types.Content(role="user", parts=parts))
        raise AssistantUnavailable(f"Stopped after {MAX_TOOL_ROUNDS} rounds of lookups without an answer.")

    def _generate(self, contents: list[Any], config: Any) -> Any:
        """One call, plus one retry after a short pause when Gemini is busy (429/503): a person is
        waiting, and these spikes usually pass in seconds. Anything else is "unavailable" at once."""
        for attempt in range(2):
            try:
                return self.client.models.generate_content(model=self.model_id, contents=contents, config=config)
            except errors.APIError as exc:
                busy = getattr(exc, "code", None) in (429, 503)
                if attempt == 0 and busy:
                    time.sleep(RETRY_PAUSE_SECONDS)
                    continue
                raise AssistantUnavailable(f"Gemini {type(exc).__name__}: {exc}") from exc
        raise AssistantUnavailable("Gemini did not answer.")



class GeminiDrafter:
    """Structured drafts (intake) and short notes with Gemini (Step 24)."""

    def __init__(self, client: Any, model_id: str):
        self.client = client
        self.model_id = model_id
        self._caller = GeminiAssistant(client, model_id)

    def json(self, system: str, text: str, schema: dict[str, Any]) -> dict[str, Any]:
        config = types.GenerateContentConfig(system_instruction=system, response_mime_type="application/json",
                                             response_json_schema=schema, max_output_tokens=4000)
        response = self._caller._generate([text], config)
        try:
            return json.loads(response.text or "")
        except ValueError as exc:
            raise AssistantUnavailable("Gemini did not return valid JSON.") from exc

    def text(self, system: str, text: str) -> str:
        config = types.GenerateContentConfig(system_instruction=system, max_output_tokens=2000)
        answer = (self._caller._generate([text], config).text or "").strip()
        if not answer:
            raise AssistantUnavailable("Gemini returned no text.")
        return answer
