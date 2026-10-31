import json
import uuid
from typing import Any

import ollama

from app.config import settings
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


class OllamaProvider(LLMProvider):
    """Fully local fallback. Small models (llama3.2 3B) work but make more SQL mistakes."""

    name = "ollama"
    supports_forced_tools = False

    def __init__(self, host: str, model: str):
        self.model = model
        self.client = ollama.Client(host=host)

    @staticmethod
    def _options(temperature: float) -> dict[str, Any]:
        return {"temperature": temperature, "num_ctx": settings.ollama_num_ctx}

    def warm(self) -> None:
        try:
            self.client.chat(
                model=self.model,
                messages=[{"role": "user", "content": "hi"}],
                options={"num_predict": 1, "num_ctx": settings.ollama_num_ctx},
                keep_alive=settings.ollama_keep_alive,
            )
        except Exception:  # noqa: BLE001 — warming is best-effort
            pass

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
                options=self._options(0.1),
                keep_alive=settings.ollama_keep_alive,
            )
        except (ollama.ResponseError, ConnectionError) as exc:
            raise LLMError(f"Ollama error: {exc}") from exc

        record_usage(response.prompt_eval_count, response.eval_count)
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
        temperature: float | None = None,
    ) -> T:
        try:
            response = self.client.chat(
                model=self.model,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                format=schema.model_json_schema(),
                options=self._options(0.2 if temperature is None else temperature),
                keep_alive=settings.ollama_keep_alive,
            )
        except (ollama.ResponseError, ConnectionError) as exc:
            raise LLMError(f"Ollama error: {exc}") from exc
        record_usage(response.prompt_eval_count, response.eval_count)
        try:
            return schema.model_validate_json(response.message.content or "")
        except ValueError as exc:
            raise LLMOutputError(f"Ollama returned output that doesn't match the schema: {exc}") from exc
