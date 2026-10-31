import json
import re
import time
from typing import Any

from google import genai
from google.genai import errors, types

from app.llm.base import (
    AgentMessage,
    LLMError,
    LLMOutputError,
    LLMProvider,
    LLMTurn,
    RetryCallback,
    T,
    ToolCall,
    ToolSpec,
    record_usage,
)

MAX_RETRIES = 2
MAX_WAIT_S = 25.0  # a longer rate-limit wait is reported to the user instead of blocking the request
MAX_TOOL_TOKENS = 1500
MAX_STRUCTURED_TOKENS = 1200
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
        return float(match.group(1) or match.group(2)) + 1.0
    return 2.0 * (2**attempt)  # 2 s, then 4 s


class GeminiProvider(LLMProvider):
    name = "gemini"
    supports_forced_tools = True

    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set in backend/.env.")
        self.model = model
        self.client = genai.Client(api_key=api_key)
        self._thinking_ok = True

    def _thinking(self) -> types.ThinkingConfig | None:
        """Reasoning tokens cost quota and latency, and SQL generation doesn't need them."""
        if not self._thinking_ok:
            return None
        if self.model.startswith("gemini-3"):
            return types.ThinkingConfig(thinking_level="MINIMAL")
        if self.model.startswith("gemini-2.5"):
            return types.ThinkingConfig(thinking_budget=0)
        return None

    def _call(self, contents: list[types.Content], config: types.GenerateContentConfig, on_retry: RetryCallback | None):
        config.thinking_config = self._thinking()
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self.client.models.generate_content(
                    model=self.model, contents=contents, config=config
                )
                usage = response.usage_metadata
                if usage is not None:
                    record_usage(usage.prompt_token_count, usage.candidates_token_count)
                return response
            except errors.APIError as exc:
                if exc.code == 400 and config.thinking_config is not None:
                    self._thinking_ok = False  # this model rejects the thinking setting; retry without it
                    config.thinking_config = None
                    continue
                retryable = exc.code in (429, 500, 503)
                delay = _retry_after(exc, attempt) if retryable else 0.0
                if not retryable or attempt == MAX_RETRIES or delay > MAX_WAIT_S:
                    if exc.code == 429:
                        wait = f" Try again in about {int(delay)}s." if delay else ""
                        raise LLMError(
                            "Gemini free-tier rate limit reached (requests or tokens per minute/day)." + wait
                        ) from exc
                    if exc.code == 503:
                        raise LLMError("Gemini is overloaded right now (503). Try again in a moment.") from exc
                    raise LLMError(f"Gemini API error {exc.code}: {exc.message or exc}") from exc
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
            max_output_tokens=MAX_TOOL_TOKENS,
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
        temperature: float | None = None,
    ) -> T:
        config = types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.2 if temperature is None else temperature,
            max_output_tokens=MAX_STRUCTURED_TOKENS,
            response_mime_type="application/json",
            response_json_schema=_inline_refs(schema.model_json_schema()),
        )
        response = self._call(
            [types.Content(role="user", parts=[types.Part.from_text(text=prompt)])], config, on_retry
        )
        try:
            return schema.model_validate(json.loads(response.text or ""))
        except (json.JSONDecodeError, ValueError) as exc:  # pydantic's ValidationError is a ValueError
            raise LLMOutputError(f"Gemini returned output that doesn't match the schema: {exc}") from exc
