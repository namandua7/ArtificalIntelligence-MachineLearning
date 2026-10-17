import json
import re
import time
from typing import Any

from google import genai
from google.genai import errors, types

from app.llm.base import (
    AgentMessage,
    LLMError,
    LLMProvider,
    LLMTurn,
    RetryCallback,
    T,
    ToolCall,
    ToolSpec,
)

MAX_RETRIES = 4
_RETRY_DELAY = re.compile(r"retry in ([\d.]+)s|\"retryDelay\":\s*\"(\d+)s\"", re.IGNORECASE)


def _inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Pydantic emits $defs/$ref for nested models; inline them so the schema is self-contained."""
    defs = schema.get("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            if "$ref" in node:
                return resolve(defs[node["$ref"].split("/")[-1]])
            return {k: resolve(v) for k, v in node.items() if k != "$defs"}
        if isinstance(node, list):
            return [resolve(v) for v in node]
        return node

    return resolve(schema)


def _retry_after(exc: errors.APIError, attempt: int) -> float:
    match = _RETRY_DELAY.search(str(exc))
    if match:
        return min(float(match.group(1) or match.group(2)) + 1.0, 60.0)
    return min(5.0 * (2**attempt), 60.0)


class GeminiProvider(LLMProvider):
    name = "gemini"
    supports_forced_tools = True

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set in backend/.env.")
        self.model = model
        self.client = genai.Client(api_key=api_key)

    def _call(self, contents: list[types.Content], config: types.GenerateContentConfig, on_retry: RetryCallback | None):
        for attempt in range(MAX_RETRIES + 1):
            try:
                return self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
            except errors.APIError as exc:
                retryable = exc.code in (429, 500, 503)
                if not retryable or attempt == MAX_RETRIES:
                    if exc.code == 429:
                        raise LLMError(
                            "Gemini free-tier rate limit reached. Wait a minute (or for the daily "
                            "quota to reset) and try again."
                        ) from exc
                    raise LLMError(f"Gemini API error {exc.code}: {exc.message or exc}") from exc
                delay = _retry_after(exc, attempt)
                if on_retry:
                    on_retry(delay, "rate limited" if exc.code == 429 else f"Gemini error {exc.code}")
                time.sleep(delay)
        raise LLMError("unreachable")

    @staticmethod
    def _to_contents(messages: list[AgentMessage]) -> list[types.Content]:
        contents: list[types.Content] = []
        for msg in messages:
            if msg.role == "user":
                contents.append(types.Content(role="user", parts=[types.Part.from_text(text=msg.text)]))
            elif msg.role == "assistant" and msg.turn is not None:
                if msg.turn.raw is not None:
                    contents.append(msg.turn.raw)
                else:
                    parts = [types.Part.from_text(text=msg.turn.text)] if msg.turn.text else []
                    parts += [
                        types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.args))
                        for c in msg.turn.tool_calls
                    ]
                    contents.append(types.Content(role="model", parts=parts))
            elif msg.role == "tool":
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part(
                                function_response=types.FunctionResponse(
                                    id=call.id, name=call.name, response=result
                                )
                            )
                            for call, result in msg.results
                        ],
                    )
                )
        return contents

    def chat_with_tools(
        self,
        system: str,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
        on_retry: RetryCallback | None = None,
    ) -> LLMTurn:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.1,
            tools=[
                types.Tool(
                    function_declarations=[
                        types.FunctionDeclaration(
                            name=t.name, description=t.description, parameters_json_schema=t.parameters
                        )
                        for t in tools
                    ]
                )
            ],
            # Force a tool call every turn: the loop ends only when the model calls final_answer.
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(mode="ANY")
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        response = self._call(self._to_contents(messages), config, on_retry)
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            reason = getattr(candidate, "finish_reason", None) if candidate else "no candidates"
            raise LLMError(f"Gemini returned no content (finish reason: {reason}).")

        text_parts = [p.text for p in candidate.content.parts or [] if p.text and not p.thought]
        calls = [
            ToolCall(id=fc.id, name=fc.name or "", args=dict(fc.args or {}))
            for fc in response.function_calls or []
        ]
        return LLMTurn(text="".join(text_parts).strip(), tool_calls=calls, raw=candidate.content)

    def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        on_retry: RetryCallback | None = None,
    ) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2,
            response_mime_type="application/json",
            response_json_schema=_inline_refs(schema.model_json_schema()),
        )
        response = self._call(
            [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])], config, on_retry
        )
        try:
            data: Any = json.loads(response.text or "")
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini returned invalid JSON: {exc}") from exc
        return schema.model_validate(data)
