import json
import uuid
from typing import Any

import ollama

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


class OllamaProvider(LLMProvider):
    """Fully local fallback. Small models (llama3.2 3B) work but make more SQL mistakes."""

    name = "ollama"
    supports_forced_tools = False

    def __init__(self, host: str, model: str):
        self.model = model
        self.client = ollama.Client(host=host)

    @staticmethod
    def _to_messages(system: str, messages: list[AgentMessage]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = [{"role": "system", "content": system}]
        for msg in messages:
            if msg.role == "user":
                out.append({"role": "user", "content": msg.text})
            elif msg.role == "assistant" and msg.turn is not None:
                out.append(
                    {
                        "role": "assistant",
                        "content": msg.turn.text,
                        "tool_calls": [
                            {"function": {"name": c.name, "arguments": c.args}} for c in msg.turn.tool_calls
                        ],
                    }
                )
            elif msg.role == "tool":
                for call, result in msg.results:
                    out.append(
                        {"role": "tool", "tool_name": call.name, "content": json.dumps(result, default=str)}
                    )
        return out

    def chat_with_tools(
        self,
        system: str,
        messages: list[AgentMessage],
        tools: list[ToolSpec],
        on_retry: RetryCallback | None = None,
    ) -> LLMTurn:
        try:
            response = self.client.chat(
                model=self.model,
                messages=self._to_messages(system, messages),
                tools=[
                    {
                        "type": "function",
                        "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
                    }
                    for t in tools
                ],
                options={"temperature": 0.1},
            )
        except (ollama.ResponseError, ConnectionError) as exc:
            raise LLMError(f"Ollama error: {exc}") from exc

        calls = []
        for tc in response.message.tool_calls or []:
            args = tc.function.arguments
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            calls.append(ToolCall(id=uuid.uuid4().hex[:8], name=tc.function.name, args=dict(args or {})))
        return LLMTurn(text=(response.message.content or "").strip(), tool_calls=calls)

    def generate_structured(
        self,
        system: str,
        prompt: str,
        schema: type[T],
        on_retry: RetryCallback | None = None,
    ) -> T:
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                format=schema.model_json_schema(),
                options={"temperature": 0.2},
            )
        except (ollama.ResponseError, ConnectionError) as exc:
            raise LLMError(f"Ollama error: {exc}") from exc
        try:
            return schema.model_validate_json(response.message.content or "")
        except ValueError as exc:
            raise LLMError(f"Ollama returned output that doesn't match the schema: {exc}") from exc
